from django.shortcuts import render, redirect
from .forms import CustomUserCreationForm, LoginForm 
from django.contrib.auth import login, authenticate, logout
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from management.forms import UserImage
from management.models import Item
# Create your views here.

def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('vendor:dashboard')
    else:
        form = CustomUserCreationForm()
    return render(request, 'users/register.html', {'form': form})

def sign_in(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            
            if user:
                login(request, user)
                messages.success(request,'Success')
                
                # --- اضافه کردن شرط برای هدایت بر اساس is_staff ---
                if user.is_staff:
                    # اگر کاربر is_staff=True بود (مدیر/فروشنده)، به پنل مدیریت برود
                    return redirect('vendor:dashboard')
                else:
                    # اگر کاربر is_staff=False بود (کاربر عادی)، به صفحه پروفایل یا صفحه اصلی برود
                    return redirect('profile') # یا redirect('home') اگر مسیر home دارید
                # ----------------------------------------------------
                
            else:
                messages.warning(request, 'Username or Password is/are Incorrect :(')
                return redirect('login')
            
    else:
        form = LoginForm()
    return render(request, 'users/login.html', {'form':form})

@login_required
def profile(request):
    return render(request, 'users/profile.html')  

def sign_out(request):
    logout(request)
    messages.info(request, 'Logged Out!!!')
    return redirect('home')



@login_required
def products_list(request):
    """
    نمایش لیست تمام محصولات موجود به کاربر وارد شده (فقط نمایش — بدون سبد/سفارش).
    خروجی: types = [
        {"code": code, "label": label, "products": queryset_of_products, "count": n},
        ...
    ]
    """
    products_qs = Item.objects.filter(is_available=True).order_by('name')

    # سعی می‌کنیم چند نام رایج برای تعریف choices را پشتیبانی کنیم
    choices = None
    for attr in ('CHOICES', 'DRINK_TYPE_CHOICES', 'TYPE_CHOICES', 'TYPES'):
        if hasattr(Item, attr):
            choices = getattr(Item, attr)
            break

    types = []
    if choices:
        for code, label in choices:
            category_products = products_qs.filter(drink_type=code)
            if category_products.exists():
                types.append({
                    "code": code,
                    "label": label,
                    "products": category_products,
                    "count": category_products.count()
                })

    # اگر هیچ CHOICES وجود نداشت: fallback — گروه‌بندی بر اساس مقادیر موجود در فیلد drink_type
    if not types:
        # استخراج انواع واقعی از queryset
        distinct_types = products_qs.values_list('drink_type', flat=True).distinct()
        for dt in distinct_types:
            category_products = products_qs.filter(drink_type=dt)
            types.append({
                "code": dt,
                "label": dt if dt else "سایر",
                "products": category_products,
                "count": category_products.count()
            })

    return render(request, 'users/products_list.html', {'types': types})