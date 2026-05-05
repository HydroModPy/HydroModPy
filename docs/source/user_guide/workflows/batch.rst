Batch Workflow
==============

``workflow = "batch"`` runs a regional-lab campaign. It expands one or more
recipes over a site catalog and records which cases were planned, skipped,
completed, or failed.

Use it when the question is:
"How do I run the same modelling recipe across many sites consistently?"

Functional Role
---------------

The batch workflow is about campaign orchestration, not about one solver
method. A batch recipe can point to simulation or comparison launchers.
The accepted launcher names are ``simulation`` and ``comparison``.

The launcher performs this type of expansion:

.. code-block:: text

   site catalog
       -> global selection filters
       -> optional cluster rules
       -> recipe selection filters
       -> case plan
       -> optional config-path validation
       -> execution or dry planning
       -> report and manifest

It is appropriate for:

- multi-basin campaigns;
- repeated deployment across clusters or regions;
- separating site inventory from run recipes;
- resuming partially completed campaigns;
- documenting what was skipped and why.

Typical Command
---------------

.. code-block:: bash

   hmp run path/to/regional_lab.toml

Public examples are currently thinner than for ``overview`` and
``simulation``. The runtime contract is nevertheless explicit: the workflow
expects a top-level ``[regional_lab]`` section.

Minimal Shape
-------------

.. code-block:: toml

   workflow = "batch"

   [regional_lab]
   lab_id = "headwater_campaign"
   output_root = "outputs/headwater_campaign"
   execute = false
   continue_on_error = true
   validate_config_paths = true
   resume_from_report = true
   skip_completed_cases = true

   [regional_lab.catalog]
   path = "site_catalog.csv"
   format = "csv"
   site_id_field = "site_id"
   site_label_field = "site_label"
   cluster_id_field = "cluster_id"
   region_field = "region_id"
   enabled_field = "enabled"
   x_field = "x"
   y_field = "y"
   area_km2_field = "area_km2"
   tags_field = "tags"

   [regional_lab.selection]
   regions = ["brittany"]
   tags = ["headwater"]
   limit = 10

   [[regional_lab.recipe]]
   id = "mf6_reference"
   label = "MODFLOW 6 reference run"
   launcher = "simulation"
   config_path_template = "sites/{site_id}/run_mf6_reference.toml"
   enabled = true

Important Parameters
--------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Section / field
     - Role
     - Practical guidance
   * - ``workflow``
     - Selects the regional-lab launcher.
     - Must be ``"batch"``.
   * - ``[regional_lab].lab_id``
     - Names the campaign.
     - Use a stable identifier because reports and output folders are keyed by
       it.
   * - ``output_root``
     - Stores campaign reports and manifests.
     - Keep it outside individual site folders.
   * - ``execute``
     - Controls dry planning versus execution.
     - Use ``false`` first to validate expansion before launching many runs.
   * - ``continue_on_error``
     - Decides whether one failed site stops the campaign.
     - Use ``true`` for large campaigns where later sites should still run.
   * - ``validate_config_paths``
     - Checks that recipe-expanded config files exist.
     - Keep enabled unless generating configs in a separate step.
   * - ``resume_from_report``
     - Reuses previous campaign status.
     - Useful for interrupted regional campaigns.
   * - ``skip_completed_cases``
     - Avoids rerunning successful cases.
     - Keep enabled for resumable campaign execution.
   * - ``[regional_lab.catalog]``
     - Describes the site inventory table.
     - Map HydroModPy's expected concepts to your CSV or JSONL field names.
   * - ``[regional_lab.selection]``
     - Filters the global site set.
     - Use regions, clusters, tags, statuses, maturity levels, or ``limit``.
   * - ``[[regional_lab.recipe]]``
     - Declares one operation expanded over selected sites.
     - ``launcher`` is currently ``simulation`` or ``comparison``.

Catalog Mental Model
--------------------

The catalog is not a model config. It is an inventory:

.. code-block:: text

   site_id,site_label,region_id,cluster_id,enabled,x,y,area_km2,tags
   nancon,Nancon,brittany,headwater,true,127348,6835802,10,headwater;demo
   vire,Vire,normandy,regional,true,400866,6923974,100,regional;mf6

Recipes then turn rows into concrete config paths:

.. code-block:: toml

   config_path_template = "sites/{site_id}/run_mf6_reference.toml"

For ``site_id = "nancon"``, this becomes:

.. code-block:: text

   sites/nancon/run_mf6_reference.toml

Planning First
--------------

For a new campaign, start with:

.. code-block:: toml

   [regional_lab]
   execute = false
   validate_config_paths = true

This produces a plan without launching expensive simulations. Only switch
``execute`` to ``true`` once the selected sites, recipes, and config paths are
correct.

Outputs To Inspect
------------------

Inspect the campaign outputs in this order:

1. planned case list;
2. skipped case list and skip reasons;
3. execution report;
4. per-recipe status counts;
5. failed case messages;
6. links to child simulation or comparison outputs.

Next Pages
----------

- :doc:`../../architecture/index`
- :doc:`simulation`
- :doc:`comparison`
- :doc:`../../getting_started/workspace-layout`
