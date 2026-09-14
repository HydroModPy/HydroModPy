{{ fullname | escape | underline}}

.. automodule:: {{ fullname }}

   {#- `members` is the module's __all__ when it declares one, so intersecting
       with it keeps autosummary_imported_members from documenting whatever the
       package happens to have imported. Without this, `typing.Any` and
       `importlib.import_module` each got their own page. -#}

   {% block attributes %}
   {% set shown = attributes | select("in", members) | list %}
   {% if shown %}
   .. rubric:: Module attributes

   .. autosummary::
      :toctree:
   {% for item in shown %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block functions %}
   {% set shown = functions | select("in", members) | list %}
   {% if shown %}
   .. rubric:: {{ _('Functions') }}

   .. autosummary::
      :toctree:
   {% for item in shown %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block classes %}
   {% set shown = classes | select("in", members) | list %}
   {% if shown %}
   .. rubric:: {{ _('Classes') }}

   .. autosummary::
      :toctree:
   {% for item in shown %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block exceptions %}
   {% set shown = exceptions | select("in", members) | list %}
   {% if shown %}
   .. rubric:: {{ _('Exceptions') }}

   .. autosummary::
      :toctree:
   {% for item in shown %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

.. The `modules` block that recursed into every submodule was removed on
   purpose. It produced 1290 pages of which 11 rendered a single Python object,
   and those empty pages owned the search index: a matching py:module scores 26
   in searchtools.js against 15 for a page title and 5 for body text. What is
   listed here is the package's declared public surface, one page each, and
   nothing else. Submodules are reachable from the source links.
