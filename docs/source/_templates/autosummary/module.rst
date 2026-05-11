{%- set skip_modules = [
    'hydromodpy.data.variables.hydrometry.discovery',
    'hydromodpy.data.variables.piezometry.discovery',
    'hydromodpy.workflow.pipelines.overview',
] -%}
{{ fullname | escape | underline}}

.. automodule:: {{ fullname }}

   {% block attributes %}
   {% if attributes %}
   .. rubric:: Module attributes

   .. autosummary::
   {% for item in attributes %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block functions %}
   {% if functions %}
   .. rubric:: {{ _('Functions') }}

   .. autosummary::
   {% for item in functions %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block classes %}
   {% if classes %}
   .. rubric:: {{ _('Classes') }}

   .. autosummary::
   {% for item in classes %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block exceptions %}
   {% if exceptions %}
   .. rubric:: {{ _('Exceptions') }}

   .. autosummary::
   {% for item in exceptions %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

{% block modules %}
{% set visible_modules = modules | reject('in', skip_modules) | list %}
{% if visible_modules %}
.. rubric:: Modules

.. autosummary::
   :toctree:
   :recursive:
{% for item in visible_modules %}
   {{ item }}
{%- endfor %}
{% endif %}
{% endblock %}
