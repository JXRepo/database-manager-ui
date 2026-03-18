from django.shortcuts import render, redirect
from django.contrib.auth import login
from apps.pages.models import Product
from django.core import serializers
from django.contrib.auth.decorators import login_required

from .models import *
from .forms import SignUpForm

@login_required
def index(request):
  context = {
    'segment': 'dashboard'
  }
  return render(request, "pages/index.html", context)

# Components
def color(request):
  context = {
    'segment': 'color'
  }
  return render(request, "pages/color.html", context)

def typography(request):
  context = {
    'segment': 'typography'
  }
  return render(request, "pages/typography.html", context)

def icon_feather(request):
  context = {
    'segment': 'feather_icon'
  }
  return render(request, "pages/icon-feather.html", context)

def sample_page(request):
  context = {
    'segment': 'sample_page',
  }
  return render(request, 'pages/sample-page.html', context)


def register_view(request):
  """Register a new user and log them in"""
  if request.method == "POST":
    form = SignUpForm(request.POST)
    if form.is_valid():
      user = form.save()
      login(request, user)
      return redirect("/")
  else:
    form = SignUpForm()

  return render(request, "accounts/register.html", {"form": form})
