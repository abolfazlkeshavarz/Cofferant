from django.db import models

# Create your models here.
class Item(models.Model):
    CHOICES = (('hot coffee', 'Hot Coffee'),
                ('cold coffee', 'Cold Coffee'),
                ('hot drink', 'Hot Drink'),
                ('cold drink', 'Cold Drink'),
                ('cakes', 'Cakes'))
    name = models.CharField(max_length=100)
    drink_type = models.CharField(max_length=100, choices=CHOICES)
    specs = models.TextField(max_length=150)
    image = models.ImageField(upload_to='images')

    def __str__(self):
        return self.name
    
