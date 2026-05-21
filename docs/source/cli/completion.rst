Shell completion
================

:command:`hmp dev completion` emits a shell completion script on stdout
for ``bash``, ``zsh``, or ``fish``. The generated script covers the
top-level subcommands, every family sub-action, and the long flags
exposed by each leaf parser. The walk runs at script-emission time, so
regenerate the script after upgrading HydroModPy.

bash
----

Source the script for the current shell, or drop it into the
system-wide completion directory for a persistent install.

.. code-block:: bash

   # current shell only
   eval "$(hmp dev completion bash)"

   # system-wide install (requires root)
   hmp dev completion bash | sudo tee /etc/bash_completion.d/hmp > /dev/null

zsh
---

Save the script under a directory listed in ``$fpath`` and run
``compinit`` once. The example uses ``~/.zsh/completions``; adapt the
path to match your dotfiles layout.

.. code-block:: bash

   mkdir -p ~/.zsh/completions
   hmp dev completion zsh > ~/.zsh/completions/_hmp
   # in ~/.zshrc, before `compinit`:
   #   fpath=(~/.zsh/completions $fpath)
   #   autoload -U compinit && compinit

fish
----

Drop the script into ``~/.config/fish/completions/``. Fish picks it up
on the next shell start; no extra step required.

.. code-block:: bash

   hmp dev completion fish > ~/.config/fish/completions/hmp.fish

Bash/zsh argcomplete integration
--------------------------------

For richer flag completion beyond what ``hmp dev completion`` ships,
install ``argcomplete`` and source its hook:

.. code-block:: bash

   pip install argcomplete
   eval "$(register-python-argcomplete hmp)"

Add the eval line to your shell rc file to keep completion active.
