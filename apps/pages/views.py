import json

from django.shortcuts import render, redirect
from django.contrib.auth import login
from apps.pages.models import Product
from django.core import serializers
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import *
from .forms import SignUpForm, JSONUploadForm


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


@login_required
def upload_json_view(request):
    """
    Upload a JSON file and unwrap data objects into database records

    Parameters
    ----------
    request : HttpRequest
        Incoming HTTP request

    Returns
    -------
    HttpResponse
        Rendered upload page or redirect after success
    """
    if request.method == "POST":
        form = JSONUploadForm(request.POST, request.FILES)

        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]

            try:
                payload = json.load(uploaded_file)
            except json.JSONDecodeError:
                messages.error(request, "Invalid JSON file")
                return render(request, "pages/upload.html", {"form": form})

            if isinstance(payload, list):
                objects = payload
            elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
                objects = payload["data"]
            else:
                messages.error(
                    request,
                    "JSON must be either a list or a dict with a 'data' list",
                )
                return render(request, "pages/upload.html", {"form": form})

            created_count = 0

            for obj in objects:
                if not isinstance(obj, dict):
                    continue

                access_type = obj.get("access_type", "c")
                if access_type not in {"c", "all"}:
                    access_type = "c"

                JSONData.objects.create(
                    owner=request.user,
                    data=obj,
                    access_type=access_type,
                )
                created_count += 1

            messages.success(
                request,
                f"Upload successful: {created_count} objects saved",
            )
            return redirect("upload_json")

    else:
        form = JSONUploadForm()

    return render(request, "pages/upload.html", {"form": form})


@login_required
def json_data_list_view(request):
    """
    Display uploaded JSON data objects for the current user

    Parameters
    ----------
    request : HttpRequest
        Incoming HTTP request

    Returns
    -------
    HttpResponse
        Rendered data list page
    """
    data_objects = JSONData.objects.filter(owner=request.user).order_by("-uploaded_at")

    context = {
        "data_objects": data_objects,
    }
    return render(request, "pages/data_list.html", context)
