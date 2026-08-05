# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

"""The DLPaC compiler: YAML policy source to a deploy manifest.

Importable as a package (`from compiler.compile import compile_policy`) so that nothing has to
put this directory on sys.path to reach it. That matters for more than tidiness: with the
directory on the path, `compile.py` sits at the top level as a module named `compile`, which
shadows the builtin of the same name for anything that imports it. As a package submodule it
is `compiler.compile`, and the shadowing cannot happen.

`compile.py` still runs directly (`python compiler/compile.py`) for anyone with the habit; it
falls back to flat imports when executed as a script rather than imported.
"""
