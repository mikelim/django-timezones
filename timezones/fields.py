import datetime

from django.db import models
from django.conf import settings
from django.utils.encoding import smart_unicode, smart_str
from django.db.models.fields import subclassing

from timezones import forms

import pytz

MAX_TIMEZONE_LENGTH = getattr(settings, "MAX_TIMEZONE_LENGTH", 100)
default_tz = pytz.timezone(getattr(settings, "TIME_ZONE", "UTC"))


assert(reduce(lambda x, y: x and (len(y) <= MAX_TIMEZONE_LENGTH),
              forms.ALL_TIMEZONE_CHOICES, True),
       "timezones.fields.TimeZoneField MAX_TIMEZONE_LENGTH is too small")

class TimeZoneField(models.CharField):
    __metaclass__ = subclassing.SubfieldBase
    
    def __init__(self, *args, **kwargs):
        defaults = {"max_length": MAX_TIMEZONE_LENGTH,
                    "default": settings.TIME_ZONE,
                    "choices": forms.PRETTY_TIMEZONE_CHOICES}
        defaults.update(kwargs)
        return super(TimeZoneField, self).__init__(*args, **defaults)
        
    def to_python(self, value):
        value = super(TimeZoneField, self).to_python(value)
        if value is None:
            return None # null=True
        return pytz.timezone(value)
        
    def get_db_prep_save(self, value):
        # Casts timezone into string format for entry into database.
        if value is not None:
            value = smart_unicode(value)
        return super(TimeZoneField, self).get_db_prep_save(value)

    def flatten_data(self, follow, obj=None):
        value = self._get_val_from_obj(obj)
        if value is None:
            value = ""
        return {self.attname: smart_unicode(value)}

    def formfield(self, **kwargs):
        defaults = {"form_class": forms.TimeZoneField}
        defaults.update(kwargs)
        return super(TimeZoneField, self).formfield(**defaults)


class LocalizedDateTimeFieldProperty(object):
    # Timezone handling happens on the getter to ensure that callable
    # LocalizedDateTimeField.timezone values gets passed a fully
    # initialized model instance. This is important for callables that
    # reference another model field for the timezone info.

    def __init__(self, field):
        self.field = field
        self.cache_attname = '_%s_cache' % self.field.name

    def __get__(self, obj, type=None):
        if obj is None:
            raise AttributeError('Can only be accessed via an instance.')

        timezone = self.field.timezone

        if self.cache_attname not in obj.__dict__:
            if callable(timezone):
                # letting callable either take no arguments or one
                # argument, the model instance being accessed.
                if hasattr(timezone, 'func_code'):
                    argcount = timezone.func_code.co_argcount
                elif hasattr(timezone, 'im_func'):
                    argcount = timezone.im_func.func_code.co_argcount - 1
                else:
                    argcount = timezone.__call__.func_code.co_argcount
                if argcount == 1:
                    timezone = timezone(obj)
                else:
                    timezone = timezone()

            if isinstance(timezone, basestring):
                try:
                    tzinfo = pytz.timezone(timezone)
                except pytz.UnknownTimeZoneError:
                    tzinfo = default_tz
            else:
                tzinfo = timezone

            dt = obj.__dict__[self.field.name]
            if not isinstance(dt, datetime.datetime):
                return dt
            if dt.tzinfo is None:
                obj.__dict__[self.cache_attname] = tzinfo.localize(dt)
            else:
                obj.__dict__[self.cache_attname] = dt.astimezone(tzinfo)
                
        return obj.__dict__[self.cache_attname]

    def __set__(self, obj, value):
        obj.__dict__[self.field.name] = self.field.to_python(value)
        # clear previously cached value if it exists
        if self.cache_attname in obj.__dict__:
            del obj.__dict__[self.cache_attname]


class LocalizedDateTimeField(models.DateTimeField):
    """
    A model field that provides automatic localized timezone support.
    timezone can be a timezone string, a ``datetime.tzinfo`` subclass
    such as those returned by ``pytz.timezone``, or a callable which
    returns either.

    Callable values for the ``timezone`` argument can optionally take
    one argument, which is the model instance being accessed. To get
    the timezone from another field on the model object, for example::

        dt = LocalizedDateTimeField(timezone=lambda i: i.timezone)
    """
    def __init__(self, verbose_name=None, name=None, timezone=None, **kwargs):
        if isinstance(timezone, basestring):
            timezone = smart_str(timezone)
        if timezone in pytz.all_timezones_set:
            self.timezone = pytz.timezone(timezone)
        else:
            self.timezone = timezone
        super(LocalizedDateTimeField, self).__init__(verbose_name, name, **kwargs)
        
    def formfield(self, **kwargs):
        defaults = {"form_class": forms.LocalizedDateTimeField}
        if (not isinstance(self.timezone, basestring) and str(self.timezone) in pytz.all_timezones_set):
            defaults["timezone"] = str(self.timezone)
        defaults.update(kwargs)
        return super(LocalizedDateTimeField, self).formfield(**defaults)
        
    def get_db_prep_save(self, value):
        "Returns field's value prepared for saving into a database."
        ## convert to settings.TIME_ZONE
        if value is not None:
            if value.tzinfo is None:
                value = default_tz.localize(value)
            else:
                value = value.astimezone(default_tz)
        return super(LocalizedDateTimeField, self).get_db_prep_save(value)
        
    def get_db_prep_lookup(self, lookup_type, value):
        "Returns field's value prepared for database lookup."
        ## convert to settings.TIME_ZONE
        if value.tzinfo is None:
            value = default_tz.localize(value)
        else:
            value = value.astimezone(default_tz)
        return super(LocalizedDateTimeField, self).get_db_prep_lookup(lookup_type, value)

    def contribute_to_class(self, cls, name):
        super(self.__class__, self).contribute_to_class(cls, name)
        setattr(cls, self.name, LocalizedDateTimeFieldProperty(self))
