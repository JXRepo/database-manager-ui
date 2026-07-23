import datetime, sys, inspect, importlib
import json

from functools import wraps

from django.db import models
from django.http import HttpResponseRedirect, HttpResponse

from rest_framework import serializers


REQUIRED_TOP_LEVEL_FIELDS = [
    "identifier",
    "title",
    "creator",
    "creator_affiliation",
    "date",
    "shared_with",
    "rights",
    "rights_holder",
    "software",
    "software_version",
    "system",
    "system_version",
    "processor_specifications",
    "input_path",
    "results_path",
    "RVE_size",
    "RVE_continuity",
    "discretization_type",
    "discretization_unit_size",
    "discretization_count",
    "mechanical_BC",
    "phase",
    "stress",
    "total_strain",
    "units",
]


class Utils:
    @staticmethod
    def get_class(config, name: str) -> models.Model:
        return Utils.model_name_to_class(config[name])

    @staticmethod
    def get_manager(config, name: str) -> models.Manager:
        return Utils.get_class(config, name).objects

    @staticmethod
    def get_serializer(config, name: str):
        class Serializer(serializers.ModelSerializer):
            class Meta:
                model = Utils.get_class(config, name)
                fields = '__all__'

        return Serializer

    @staticmethod
    def model_name_to_class(name: str):

        model_name = name.split('.')[-1]
        model_import = name.replace('.' + model_name, '')

        module = importlib.import_module(model_import)
        cls = getattr(module, model_name)

        return cls


def check_permission(function):
    @wraps(function)
    def wrap(viewRequest, *args, **kwargs):

        try:

            # Check user
            if viewRequest.request.user.is_authenticated:

                return function(viewRequest, *args, **kwargs)

            # For authentication for guests
            return HttpResponseRedirect('/login/')

        except Exception as e:

            # On error
            return HttpResponse('Error: ' + str(e))

    return wrap


def _is_empty_required_value(value):
    """
    Return True when a required top-level field value is empty

    Parameters
    ----------
    value : object
        Field value from one JSON object

    Returns
    -------
    bool
        True when the value is empty
    """
    if value is None:
        return True

    if isinstance(value, str) and not value.strip():
        return True

    if isinstance(value, (list, dict)) and len(value) == 0:
        return True

    return False



def validate_json(data):
    """
    Validate JSON objects using required top-level fields only

    Parameters
    ----------
    data : list of dict
        Parsed JSON data objects

    Returns
    -------
    valid_data : list of dict
        Valid objects that contain all required top-level fields

    errors : list of str
        Validation error messages
    """
    valid_data = []
    errors = []

    for index, obj in enumerate(data, start=1):
        if not isinstance(obj, dict):
            errors.append(f"Data object {index}: not a valid JSON object")
            continue

        missing_fields = []
        empty_fields = []

        for field in REQUIRED_TOP_LEVEL_FIELDS:
            if field not in obj:
                missing_fields.append(field)
            elif _is_empty_required_value(obj.get(field)):
                empty_fields.append(field)

        if missing_fields or empty_fields:
            missing_label = "field" if len(missing_fields) == 1 else "fields"
            empty_label = "field" if len(empty_fields) == 1 else "fields"

            if missing_fields and not empty_fields:
                errors.append(
                    f"Data object {index}: missing required {missing_label}: "
                    f"{', '.join(missing_fields)}. "
                    f"Please add the missing required {missing_label} and upload the JSON file again."
                )
            elif empty_fields and not missing_fields:
                errors.append(
                    f"Data object {index}: empty required {empty_label}: "
                    f"{', '.join(empty_fields)}. "
                    f"Please fill in the empty required {empty_label} and upload the JSON file again."
                )
            else:
                errors.append(
                    f"Data object {index}: missing required "
                    f"{'field' if len(missing_fields) == 1 else 'fields'}: "
                    f"{', '.join(missing_fields)}; "
                    f"empty required "
                    f"{'field' if len(empty_fields) == 1 else 'fields'}: "
                    f"{', '.join(empty_fields)}. "
                    f"Please add the missing required fields and fill in the empty required fields, "
                    f"then upload the JSON file again."
                )
            continue


        valid_data.append(obj)

    return valid_data, errors
