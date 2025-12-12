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
                return redirect('vendor:dashboard')
            else:
                messages.warning(request, 'Username or Password is/are Incorrect :(')
                return redirect('login')
            
    else:
        form = LoginForm()
    return render(request, 'users/login.html', {'form':form})

@login_required
def profile(request):
    if request.method == 'POST':  
        form = UserImage(request.POST, request.FILES)  
        if form.is_valid():  
            form.save()  
  
            # Getting the current instance object to display in the template  
            img_object = form.instance  
              
            return render(request, 'users/profile.html', {'form': form, 'img_obj': img_object})  
    else:  
        form = UserImage()  
  
    return render(request, 'users/profile.html', {'form': form})  

def sign_out(request):
    logout(request)
    messages.info(request, 'Logged Out!!!')
    return redirect('home')