from django.shortcuts import render, redirect
from .forms import CustomUserCreationForm
from django.contrib.auth import login

# Create your views here.
def profile(request):
    return render(request, 'users/profile.html')

def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('profile')
    else:
        form = CustomUserCreationForm()
    return render(request, 'users/register.html', {'form': form})

