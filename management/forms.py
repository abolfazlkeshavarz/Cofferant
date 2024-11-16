from django import forms
from . import models

class UserImage(forms.ModelForm):
    class Meta:
        model = models.Item
        fields = '__all__'
        widgets = {
                'name': forms.TextInput(attrs={
                    'class': "input-group mb-3 input-group-text",
                    'id':"basic-addon1",
                    'style': "margin-left: auto; margin-right: auto; display: block; text-align: center; width:250px;",
                    'placeholder': 'عنوان'
                }),
                'specs': forms.Textarea(attrs={
                    'class': "input-group mb-3 input-group-text",
                    'id':"basic-addon1",
                    'style': "margin-right: auto; margin-right: auto; display: block; text-align: center; width:100%;",
                    'placeholder': 'جزئیات'
                }),
                }
        