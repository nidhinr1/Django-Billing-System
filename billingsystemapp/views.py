from django.shortcuts import render,get_object_or_404,redirect
from . models import Category,Product,Sales,stock,Billing
from django.contrib.auth.models import User,auth
from django.contrib.auth.decorators import login_required,user_passes_test
from django.contrib.auth import authenticate, login,logout
from django.http import JsonResponse,HttpResponse,FileResponse
from datetime import datetime,timedelta,date
from django.contrib import messages
from django.db.models import Q,Sum
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle,Paragraph,Spacer,Image
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
import io,uuid
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import IntegrityError

def addcategory(request):
    if request.method =='POST':
        category=request.POST['category']
        q=Category(name=category)
        q.save()
        return render(request,'addcategory.html',{'msg':'Category submitted'})
    else:
        return render(request,'addcategory.html')
    
def adduser(request):
    if request.method =='POST':
        username=request.POST['username']
        password=request.POST['password']
        if User.objects.filter(username = username).exists():
            return render(request,'adduser.html',{'msg':'username or email aready exist.'})
        else:
            q=User.objects.create_user(username=username,password=password)
            q.save()
        return render(request,'adduser.html',{'msg':'User Added'})
    else:
        return render(request,'adduser.html')

def addproduct(request):
    types = Category.objects.all().values()
    if request.method == 'POST':
        name = request.POST['pdtname']
        brand = request.POST['brand']
        price = float(request.POST['pdtprice'])
        stock_quantity = request.POST['pdtstock']
        category_name = request.POST['pdtcategory']
        manufacturing = request.POST['pdtmanu']

        category = get_object_or_404(Category, name=category_name)

        # Create Product instance
        product = Product(
            product_name=name,
            brand=brand,
            price=price,
            quantity=stock_quantity,
            category=category,
            manufacturingdate=manufacturing
        )
        product.save()

        # Create Stock instance
        stock_entry = stock(
            product_name=product,  # Link to the Product instance
            category=category,
            stock=stock_quantity,
            price = round(price * 0.95, 2)
        )
        stock_entry.save()

        return render(request, 'addproduct.html', {'msg': 'Product and Stock submitted', 'type': types})
    else:
        return render(request, 'addproduct.html', {'type': types})

def billing(request):
    if request.method == 'POST':
        if 'add_product' in request.POST:
            product_id = request.POST.get('product_id')
            quantity = request.POST.get('quantity')
            product = get_object_or_404(Product, pk=product_id)
            cart = request.session.get('cart', {})
            
            if product.quantity == 0:
                return render(request, 'billing.html', {
                    'msg': f'{product.product_name} is out of stock.',
                    'products': Product.objects.all(),
                    'cart': cart,
                    'total_price': round_to_two_decimal_places(sum(item['discounted_price'] * item['quantity'] for item in cart.values())),
                })

            try:
                quantity = int(quantity)
                if product_id in cart:
                    new_quantity = cart[product_id]['quantity'] + quantity
                else:
                    new_quantity = quantity

                if new_quantity > product.quantity:
                    return render(request, 'billing.html', {
                        'msg': f'Quantity requested for {product.product_name} exceeds stock available ({product.quantity}).',
                        'products': Product.objects.all(),
                        'cart': cart,
                        'total_price': round_to_two_decimal_places(sum(item['discounted_price'] * item['quantity'] for item in cart.values())),
                    })

                discounted_price = round_to_two_decimal_places(float(product.price) * (1 - (float(product.discount) / 100)))

                if product_id in cart:
                    cart[product_id]['quantity'] += quantity
                else:
                    cart[product_id] = {
                        'name': product.product_name,
                        'original_price': round_to_two_decimal_places(float(product.price)),
                        'discounted_price': round_to_two_decimal_places(discounted_price),
                        'quantity': quantity
                    }
                request.session['cart'] = cart
            except (ValueError, Product.DoesNotExist):
                pass

        elif 'remove_product' in request.POST:
            product_id = request.POST.get('product_id')
            cart = request.session.get('cart', {})
            if product_id in cart:
                del cart[product_id]
            request.session['cart'] = cart

        elif 'submit_bill' in request.POST:
            customer_name = request.POST.get('customer_name')
            customer_address = request.POST.get('customer_address')
            customer_phone = request.POST.get('customer_phone')
            payment_method = request.POST.get('payment_method')
            cart = request.session.get('cart', {})
            sale_number = str(uuid.uuid4())
            purchasetime = datetime.now()

            try:
                for product_id, item in cart.items():
                    product = get_object_or_404(Product, pk=product_id)
                    if item['quantity'] > product.quantity:
                        error_message = f"Quantity for {product.product_name} exceeds available stock ({product.quantity})."
                        return render(request, 'billing.html', {
                            'products': Product.objects.all(),
                            'cart': cart,
                            'total_price': round_to_two_decimal_places(sum(item['discounted_price'] * item['quantity'] for item in cart.values())),
                            'error_message': error_message,
                        })

                    Billing.objects.create(
                        sale_number=sale_number,
                        product_id=product,
                        quantity=item['quantity'],
                        price=item['discounted_price'],
                        purchasetime=purchasetime,
                        customer_name=customer_name,
                        customer_address=customer_address,
                        customer_phone=customer_phone,
                        payment_method=payment_method
                    )
                    product.quantity -= item['quantity']
                    product.save()

                response = generate_pdf_bill(
                    sale_number=sale_number,
                    cart=cart,
                    purchasetime=purchasetime,
                    customer_name=customer_name,
                    customer_address=customer_address,
                    customer_phone=customer_phone,
                    payment_method=payment_method
                )

                request.session['cart'] = {}
                request.session['sale_number'] = None
                return response
            

            except IntegrityError:
                error_message = "You cannot add the same product twice in the same bill."
                return render(request, 'billing.html', {
                    'products': Product.objects.all(),
                    'cart': cart,
                    'total_price': round_to_two_decimal_places(sum(item['discounted_price'] * item['quantity'] for item in cart.values())),
                    'error_message': error_message,
                })

        elif 'create_new_transaction' in request.POST:
            request.session['cart'] = {}
            request.session['sale_number'] = None
            return redirect('billing')

    cart = request.session.get('cart', {})
    total_price = round_to_two_decimal_places(sum(item['discounted_price'] * item['quantity'] for item in cart.values()))

    return render(request, 'billing.html', {
        'products': Product.objects.all(),
        'cart': cart,
        'total_price': round_to_two_decimal_places(total_price),
    })



def round_to_two_decimal_places(value):
    return round(value, 2)


def generate_pdf_bill(sale_number, cart, purchasetime, customer_name, payment_method, customer_phone, customer_address):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="bill_{sale_number}.pdf"'

    doc = SimpleDocTemplate(response, pagesize=letter, rightMargin=72, leftMargin=72)
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles['Title']
    company_title_style = ParagraphStyle(name='CompanyTitle', fontSize=22, alignment=1)
    invoice_title_style = ParagraphStyle(name='InvoiceTitle', fontSize=16, alignment=1)
    add_style = ParagraphStyle(name='add_style', fontSize=14, alignment=1)
    normal_style = styles['Normal']
    Left_style = ParagraphStyle(name='LeftStyle', alignment=0, leftIndent=.01)
    details_style = ParagraphStyle(name='DetailsStyle', fontSize=12, alignment=0)

    logo_path = r"D:\myproject\myenv\Scripts\billingsystemproject\billingsystemapp\templates\static\png2.png"  # Adjust path as per your project structure
    logo_width = 130  # Adjust the width as needed
    logo_height = 80
    logo = Image(logo_path, width=logo_width, height=logo_height)

    company_title_style = ParagraphStyle(
        name='CompanyTitle',
        fontSize=32,  # Increase font size
        alignment=1,  # Center alignment
        textColor=colors.HexColor('#0b55f6'),   # Set the color for the text #1d2b64
        fontName='Helvetica-Bold' 
    )
    invoice_title_style = ParagraphStyle(
        name='InvoiceTitle',
        fontSize=20,  # Increase font size
        alignment=1,  # Center alignment
        textColor=colors.HexColor('#0b55f6'),   # Set the color for the text #1d2b64
        fontName='Helvetica-Bold' 
    )


    # Add company name and address
    company_name = "W A ENTERPRISE "
    company_title = Paragraph(company_name, company_title_style)
    address = Paragraph("Your trusted destination for cutting-edge electronics and unbeatable deals.", add_style)

    # Create a table to hold the company name, address, and logo in one row
    data = [
         [
            Table([
                [company_title],
                [Spacer(1, 12)],
                [address]
            ], colWidths=[300]),  # Adjust the width as needed
            logo
        ]
    ]
    table = Table(data, colWidths=[400, 100])  # Adjust colWidths as needed
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-2, -1), 'TOP'),  # Align the content to the top
    ]))
    elements.append(Spacer(1, -40))
    
    elements.append(table)
    
    elements.append(Spacer(1, 6))
    #elements.append(Paragraph("GstIN:08AALCR2857A1ZD", Left_style))
    data = [
        [
            
            Paragraph("Address: Near Attingal KSRTC bus stand, Attingal, Trivandrum, Kerala, Pincode: 695305.  GstIN:08AALCR2857A1ZD", normal_style),
            Spacer(1, 14),  # Spacer to push the next item to the right
            Paragraph("Phone: 9633477499 Email:waenterprise@gmail.com  Website:waenterprise.com"  , normal_style),

        ]
    ]
    
    table = Table(data, colWidths=[240, 100, 160])  # Adjust colWidths as needed
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    details_style = ParagraphStyle(name='DetailsStyle', fontSize=10, alignment=0)
    elements.append(table)
    elements.append(Spacer(1, 6))
     
   
    # Add main title
    main_title = Paragraph("Purchase Invoice", invoice_title_style)
    elements.append(main_title)
    elements.append(Spacer(1, 30))

    details_data = [
    [
        # Left Side: Customer details
        Paragraph(f"Customer Name: {customer_name}", normal_style),
        Paragraph(f"Purchase Date: {purchasetime.strftime('%Y-%m-%d')}", normal_style)
    ],
    [
        Paragraph(f"Customer Phone: {customer_phone}", normal_style),
        Paragraph(f"Purchase Time: {purchasetime.strftime('%H:%M:%S')}", normal_style)
    ],
    [
        Paragraph(f"Customer Address: {customer_address}", normal_style),
        Paragraph(f"Payment Method: {payment_method}", normal_style),
        
    ]
]


    
    table = Table(details_data, colWidths=[240, 260, 160])  # Narrower left column, wider right column
    table.setStyle(TableStyle([
    ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # Align left column to the left
    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),  # Align right column to the right
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Vertical alignment in the middle,
    ('LEFTPADDING', (1, 0), (1, -1), 110),
]))
    details_style = ParagraphStyle(name='DetailsStyle', fontSize=10, alignment=0)
    elements.append(table)
    elements.append(Spacer(1, 7))


    elements.append(Spacer(1, 10))
    # Table data
    data = [
        ["Sr.No","Product Name", "Qty", "Rate(Rs)", "Disc.Rate(Rs)", "Total(Rs)"]
    ]

    serial_number = 1
    total_quantity=0
    for item in cart.values():
     total_price = round(item['discounted_price'] * item['quantity'], 2)
     total_quantity=total_quantity+item['quantity']
     data.append([
        serial_number,
        item['name'],
        item['quantity'],
        f" {round(item['original_price'], 2)}",
        f" {round(item['discounted_price'], 2)}",
        f" {total_price}"
    ])
     serial_number += 1 

    subtotal = round(sum(item['discounted_price'] * item['quantity'] for item in cart.values()), 2)
    tax = round(subtotal * 0.18, 2)  # Assuming an 18% tax rate
    final_total = round(subtotal + tax, 2)

# Add rows for Total, Tax, and Final Amount
    data.append(["", "", f"{total_quantity}", "", "", f" {subtotal}"])
    
# Create the table with appropriate column widths
    table = Table(data, colWidths=[0.5 * inch, 3.40 * inch, 0.75 * inch, 1 * inch, 1 * inch, 1 * inch])

# Set the table style
    table.setStyle(TableStyle([
    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ('TOPPADDING', (0, 0), (-1, -1), 12),  # Increase height of each row
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))

    elements.append(table)

    elements.append(Spacer(1, 20))
    spacer_width = 4.5 * inch  # Adjust this width as necessary
    elements.append(Spacer(spacer_width, 0))

    summary_data = [
    ["Tax (18%):",f"Rs {tax}"],
    ["Subtotal :",f"Rs {subtotal}"],
    ["Final Amount:",f"Rs {final_total}"],
]

# Create the summary table with tight column widths
    summary_table = Table(summary_data, colWidths=[1.25 * inch, 1.0 * inch])  # Narrow column widths

# Set the table style with minimal padding
    summary_table.setStyle(TableStyle([
    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),  # Align left column (labels) to the left
    ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),  # Align right column (values) to the right
    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),  # Minimize padding
    ('TOPPADDING', (0, 0), (-1, -1), 0),
    ('LEFTPADDING', (0, 0), (-1, -1), 2),  # Minimal padding
    ('RIGHTPADDING', (0, 0), (-1, -1), 2),  # Minimal padding
    ('GRID', (0, 0), (-1, -1), 0.5, colors.white),  # Optional: Add grid lines if needed
]))
    
    spacer_width = 4.5 * inch  # Adjust this value to move the table further right
    spacer = Spacer(spacer_width, 0)

# Create a container table to position the summary table on the right
    container_data = [
    [spacer, summary_table]  # Use Spacer object here
]

# Create the container table
    container_table = Table(container_data, colWidths=[3.8 * inch])  # Adjust widths accordingly

# Set the container table style to right-align content
    container_table.setStyle(TableStyle([
    ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),  # Align content to the right
]))

# Add the container table to elements
    elements.append(container_table)
    # Add customer and payment details
    elements.append(Spacer(1, 12))

    term_title_style = ParagraphStyle(name='CompanyTitle', fontSize=10)
    terms = Paragraph("**Terms and Conditions**", term_title_style)
    terms1 = Paragraph("1. Customer should pay the due amount within 15 days", normal_style)
    terms2 = Paragraph("2. Goods once sold shall not be returned", normal_style)
    terms3 = Paragraph("3. Our responsibility ceases as soon as the goods leave our premises", normal_style)
    elements.append(Spacer(1, 24))
    elements.append(terms)
    elements.append(terms1)
    elements.append(terms2)
    elements.append(terms3)

    # Add thank you message
    thank_you_message = Paragraph("Thank you for your purchase! Have a great day!", normal_style)
    elements.append(Spacer(1, 24))
    elements.append(thank_you_message)

    def draw_border(canvas, doc):
        canvas.saveState()
        width, height = letter
        canvas.setStrokeColor(colors.black)
        canvas.setLineWidth(1)
        canvas.rect(20, 30, width - 45, height - 60)  # Adjusting margins
        canvas.restoreState()

    def draw_lines(canvas, doc):
        canvas.saveState()
        width, height = letter
        canvas.setStrokeColor(colors.black)
        canvas.setLineWidth(0.5)
        # Draw horizontal lines
        canvas.line(20, height - 125, width - 25, height - 125)
        canvas.line(20, height - 175, width - 25, height - 175)
        canvas.line(20, height - 210, width - 25, height - 210) 
        # Add more lines as needed
        canvas.restoreState()

    # Build the document with the onPage callback to draw the border and lines
    doc.build(elements, onFirstPage=lambda canvas, doc: [draw_border(canvas, doc), draw_lines(canvas, doc)],
              onLaterPages=draw_border)

    return response




def product_list(request):
    now = timezone.now().date()
    products = Product.objects.all()

    # Calculate cutoff date for new stock
    six_months_ago = now - timezone.timedelta(days=6*30)  # Approximate 6 months

    # Pass products and cutoff date to template
    return render(request, 'products.html', {
        'products': products,
        'six_months_ago': six_months_ago,
    })

def product_search(request):
    query = request.GET.get('q')
    if query:
        products = Product.objects.filter(product_name__icontains=query)
    else:
        products = Product.objects.all()
    return render(request, 'products.html', {'products': products})

def product_update(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    if request.method == 'POST':
        # Update Product details
        product.product_name = request.POST.get('product_name')
        product.brand = request.POST.get('brand')
        product.price = float(request.POST.get('price'))
        product.discount = request.POST.get('discount')
        product.quantity = request.POST.get('quantity')
        product.manufacturingdate = request.POST.get('pdtmanu')
        category_id = request.POST.get('category')
        product.category = get_object_or_404(Category, pk=category_id)
        product.save()

        # Update Stock details
        stock_item = get_object_or_404(stock, product_name=product)
        stock_item.price = round(product.price * 0.95, 2)  # Sync stock price with product price
        stock_item.stock = product.quantity  # Sync stock quantity with product quantity
        stock_item.save()

        return redirect('product')

    categories = Category.objects.all()
    return render(request, 'product_update.html', {'product': product, 'categories': categories})


def product_delete(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    if request.method == 'POST':
        product.delete()
        return redirect('product')
    return render(request, 'product_delete.html', {'product': product})

def category_list(request):
    categories = Category.objects.all()
    return render(request, 'category_list.html', {'categories': categories})

def category_delete(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    if request.method == 'POST':
        category.delete()
        return redirect('category_list')
    return render(request, 'category_delete.html', {'category': category})

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('billing')
        else:
            messages.error(request, 'Invalid username or password')
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('login')  

def user_list(request):
    users = User.objects.exclude(is_superuser=True)
    return render(request, 'user_list.html', {'users': users})

@user_passes_test(lambda u: u.is_superuser)
def user_delete(request, user_name):
    user = get_object_or_404(User, username=user_name)
    if request.method == "POST":
        user.delete()
        messages.success(request, f'User {user_name} has been deleted.')
        return redirect('user_list')
    return render(request, 'user_delete.html', {'user': user})

def search_products(request):
    query = request.GET.get('q', '')
    if query:
        products = Product.objects.filter(product_name__icontains=query)
    else:
        products = Product.objects.all()
    
    return render(request, 'products.html', {'products': products, 'query': query})

def products_search_by_category(request):
    category_query = request.GET.get('category')
    products = []

    if category_query:
        try:
            category = Category.objects.get(name__iexact=category_query)
            products = Product.objects.filter(category=category)
        except Category.DoesNotExist:
            products = Product.objects.none()
    else:
        products = Product.objects.all()
        
    return render(request, 'products.html', {'products': products, 'category_query': category_query})

@require_POST
def update_discounts_view(request):
    products = Product.objects.all()
    for product in products:
        product.update_discount()
    
    return redirect('product')

def filter_products(request, stock_type):
    six_months_ago = date.today() - timedelta(days=6*30)  # Approximate 6 months

    if stock_type == 'new':
        products = Product.objects.filter(manufacturingdate__gte=six_months_ago)
    elif stock_type == 'old':
        products = Product.objects.filter(manufacturingdate__lt=six_months_ago)
    else:
        products = Product.objects.all()

    return render(request, 'products.html', {'products': products, 'stock_type': stock_type ,'sixmonths':six_months_ago})

def sales_summary(request):
    sales = Billing.objects.all()
    total_products_sold = sales.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_money_earned = sales.aggregate(Sum('price'))['price__sum'] or 0
    total_money_earned=round_to_two_decimal_places(total_money_earned)
    context = {
        'sales': sales,
        'total_products_sold': total_products_sold,
        'total_money_earned': total_money_earned,
    }
    return render(request, 'sales_summary.html', context)

def sales_today(request):
    today = datetime.now().date()
    sales = Billing.objects.filter(purchasetime__date=today)
    total_products_sold = sales.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_money_earned = sales.aggregate(Sum('price'))['price__sum'] or 0
    total_money_earned=round_to_two_decimal_places(total_money_earned)
    context = {
        'sales': sales,
        'total_products_sold': total_products_sold,
        'total_money_earned': total_money_earned,
    }
    return render(request, 'sales_summary.html', context)

def sales_this_week(request):
    start_of_week = datetime.now().date() - timedelta(days=datetime.now().weekday())
    sales = Billing.objects.filter(purchasetime__date__gte=start_of_week)
    total_products_sold = sales.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_money_earned = sales.aggregate(Sum('price'))['price__sum'] or 0
    total_money_earned=round_to_two_decimal_places(total_money_earned)
    context = {
        'sales': sales,
        'total_products_sold': total_products_sold,
        'total_money_earned': total_money_earned,
    }
    return render(request, 'sales_summary.html', context)


def product_stock_view(request):
    products = Product.objects.all()
    product_details = []
    total_unsold_products = 0
    total_sold_products = 0
    total_stock = 0

    for product in products:
        try:
            stock_item = stock.objects.get(product_name=product)
            products_sold = stock_item.stock - product.quantity  # Updated calculation
            
            stock_type = 'New Stock' if product.manufacturingdate and product.manufacturingdate > timezone.now().date() - timedelta(days=180) else 'Old Stock'
            
            # Update totals
            total_unsold_products += product.quantity
            total_sold_products += products_sold
            total_stock += stock_item.stock

            product_details.append({
                'product': product,
                'stock': stock_item,
                'products_sold': products_sold,
                'stock_type': stock_type,
            })

        except stock.DoesNotExist:
            # Handle the case where no stock item exists for the product
            product_details.append({
                'product': product,
                'stock': None,  # No stock information available
                'products_sold': None,  # No products sold information available
                'stock_type': 'Unknown',  # Or any default value you prefer
            })

    context = {
        'product_details': product_details,
        'total_unsold_products': total_unsold_products,
        'total_sold_products': total_sold_products,
        'total_stock': total_stock,
    }

    return render(request, 'product_stock.html', context)


def profit_loss_view(request):
    billings = Billing.objects.select_related('product_id')
    total_profit_loss = 0
    profit_loss_details = []

    for billing in billings:
        stock_item = stock.objects.get(product_name=billing.product_id)
        profit_or_loss = (billing.price - stock_item.price) * billing.quantity
        total_profit_loss += profit_or_loss
        profit_loss_details.append({
            'product': billing.product_id,
            'billing_price': billing.price,
            'stock_price': stock_item.price,
            'profit_or_loss': profit_or_loss
        })

    context = {
        'profit_loss_details': profit_loss_details,
        'profit_loss': total_profit_loss
    }
    
    return render(request, 'profit_loss.html', context)


def profit_loss_today(request):
    today = datetime.now().date()
    billings = Billing.objects.filter(purchasetime__date=today).select_related('product_id')
    todays_profit_loss = 0
    profit_loss_details = []

    for billing in billings:
        stock_item = stock.objects.get(product_name=billing.product_id)
        profit_or_loss = (billing.price - stock_item.price) * billing.quantity
        todays_profit_loss += profit_or_loss
        profit_loss_details.append({
            'product': billing.product_id,
            'billing_price': billing.price,
            'stock_price': stock_item.price,
            'profit_or_loss': profit_or_loss
        })

    context = {
        'profit_loss_details': profit_loss_details,
        'profit_loss': todays_profit_loss
    }

    return render(request, 'profit_loss.html', context)


