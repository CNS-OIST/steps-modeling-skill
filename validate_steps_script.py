#!/usr/bin/env python3
"""Static validator for STEPS API_2 (steps.interface) modelling scripts.

Catches the cardinal-rule pitfalls from the steps-modeling skill WITHOUT running the
script (pure AST + regex, no side effects, STEPS not required), and for each issue
prints a concrete **fix** suggestion:

  - import order / mixing API_1 with API_2
  - `.Create()` used where its `name = X.Create(...)` source-line magic breaks
    (loops, comprehensions, multi-line, no assignment)
  - reserved Species names
  - units & biological scale: Conc (molar), Diffusion (m^2/s), mesh scale=
  - newRun / toSave / run ordering
  - reaction rate constants (`r['k'].K`) declared but never set

    python validate_steps_script.py model.py [more.py ...]   # or --selftest

Each issue is (severity, line, problem, fix). Exit 0 if no ERRORs, 1 otherwise;
WARNINGs never fail the run.
"""
import ast
import pathlib
import re
import sys

RESERVED = {"A", "V", "D", "I", "Ves", "Raft", "Vesicle"}   # reserved object names
STEPS_SUBMODS = "model|geom|sim|rng|saving|interface|visual"
LOADERS = ("LoadGmsh", "LoadAbaqus", "LoadTetGen", "LoadVTK")


def _import_checks(lines):
    out, steps_imports, iface = [], [], None
    for i, ln in enumerate(lines, 1):
        if re.match(r"\s*import\s+steps\.interface\b", ln):
            iface = i
        elif re.match(rf"\s*(from|import)\s+steps\.({STEPS_SUBMODS})\b", ln):
            steps_imports.append(i)
        if re.match(rf"\s*import\s+steps\.({STEPS_SUBMODS})\s+as\b", ln):
            out.append(("ERROR", i, "API_1-style aliased steps import",
                        "use `import steps.interface` then `from steps.<mod> import *`"))
        if re.search(r"steps\.(mpi\.)?solver\b", ln):
            out.append(("ERROR", i, "`steps.solver` is the API_1 solver",
                        "create the solver as `Simulation('Tetexact', mdl, geom, rng)`"))
        if re.search(r"\.(set|get)(Comp|Patch|Tet|Tri|Vert)\w*\s*\(", ln):
            out.append(("ERROR", i, "API_1 solver method (setComp.../getPatch...)",
                        "use sim-path access, e.g. `sim.<comp>.<Spec>.Count` / `.Conc`"))
    if steps_imports and iface is None:
        out.append(("ERROR", steps_imports[0], "missing `import steps.interface`",
                    "add `import steps.interface` as the FIRST steps import"))
    elif iface and steps_imports and iface > min(steps_imports):
        out.append(("ERROR", iface, "`import steps.interface` comes after other steps imports",
                    "move `import steps.interface` above every other `steps.*` import"))
    return out


def _is_create(call):
    return isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
        and call.func.attr == "Create"


def _create_class(call):
    f = call.func.value
    return f.id if isinstance(f, ast.Name) else "X"


def _ast_checks(tree):
    out = []
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

    def in_loop_or_comp(node):
        n = node
        while n in parents:
            n = parents[n]
            if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.SetComp,
                              ast.DictComp, ast.GeneratorExp)):
                return True
            if isinstance(n, (ast.FunctionDef, ast.Module)):
                return False
        return False

    good = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_create(node.value):
            cls = _create_class(node.value)
            ok_targets = all(isinstance(t, (ast.Name, ast.Tuple)) for t in node.targets)
            single_line = getattr(node, "end_lineno", node.lineno) == node.lineno
            if ok_targets and not in_loop_or_comp(node.value):
                good.add(node.value)
                if not single_line:
                    out.append(("WARNING", node.lineno,
                                ".Create() spans multiple lines",
                                f"keep the whole `name = {cls}.Create(...)` on one line "
                                "(it reads the source line for the name)"))
            if cls == "Species":
                for t in node.targets:
                    for e in (t.elts if isinstance(t, ast.Tuple) else [t]):
                        if isinstance(e, ast.Name) and e.id in RESERVED:
                            out.append(("ERROR", node.lineno,
                                        f"Species name '{e.id}' is reserved in STEPS",
                                        "rename to a descriptive multi-letter name (e.g. Ca, IP3)"))
                        elif isinstance(e, ast.Name) and len(e.id) == 1 and e.id.isupper():
                            out.append(("WARNING", node.lineno,
                                        f"single-letter Species name '{e.id}' may clash with a reserved name",
                                        "use a longer descriptive name"))

    for node in ast.walk(tree):
        if _is_create(node) and node not in good:
            cls = _create_class(node)
            if in_loop_or_comp(node):
                out.append(("WARNING", node.lineno,
                            f"{cls}.Create() inside a loop/comprehension can't infer a name",
                            f"call the constructor directly: `{cls}(..., name=...)`"))
            else:
                out.append(("WARNING", node.lineno,
                            f"{cls}.Create() is not assigned to a name",
                            f"assign it: `obj = {cls}.Create(...)`"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in LOADERS:
            if not any(k.arg == "scale" for k in node.keywords):
                out.append(("WARNING", node.lineno, f"{node.func.attr}() has no scale=",
                            "pass scale= so coords become metres (1e-9 for nm, 1e-6 for µm)"))
    return out


def _flow_checks(lines):
    out = []
    def first(pat):
        return next((i for i, ln in enumerate(lines, 1) if re.search(pat, ln)), None)
    run, new, save = first(r"\.run\s*\("), first(r"\.newRun\s*\("), first(r"\.toSave\s*\(")
    if run and not new:
        out.append(("ERROR", run, "`.run()` with no prior `.newRun()`",
                    "call `sim.newRun()` (resets state) before `sim.run(...)`"))
    if run and new and new > run:
        out.append(("WARNING", new, "`.newRun()` appears after `.run()`",
                    "move `sim.newRun()` before the first `sim.run(...)`"))
    if run and save and save > run:
        out.append(("WARNING", save, "`.toSave()` after `.run()` — data won't be recorded",
                    "register ResultSelectors with `sim.toSave(...)` before `sim.run(...)`"))
    return out


def _reaction_checks(src):
    out = []
    used = {m.group(2): src[:m.start()].count("\n") + 1
            for m in re.finditer(r"\br\[(['\"])(\w+)\1\]", src)}
    have_K = {m.group(2) for m in re.finditer(r"\br\[(['\"])(\w+)\1\]\s*\.\s*K\b", src)}
    for key, line in used.items():
        if key not in have_K:
            out.append(("WARNING", line, f"reaction r['{key}'] never gets a rate constant",
                        f"set it: `r['{key}'].K = kf` (or `kf, kb` if reversible)"))
    return out


def _num(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _num(node.operand)
        return None if v is None else -v
    return None


def _scale_checks(tree):
    """Units / biological scale. STEPS is SI (Diffusion m^2/s, mesh scale -> metres),
    but Conc is MOLAR (mol/L)."""
    out = []
    COMMON_SCALE = {1.0, 1e-1, 1e-2, 1e-3, 1e-6, 1e-9, 1e-12}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr == "Conc" and (v := _num(node.value)) is not None:
                    if v > 1.0:
                        out.append(("WARNING", node.lineno, f"Conc {v:g} M is non-physiological",
                                    "Conc is molar (mol/L): write 150 µM as `150e-6`"))
                    elif 0 < v < 1e-11:
                        out.append(("WARNING", node.lineno, f"Conc {v:g} M is below ~10 pM",
                                    "check units — Conc is mol/L, not mol/m³"))
                    elif v <= 0:
                        out.append(("WARNING", node.lineno, f"Conc {v:g} M is non-positive",
                                    "set a positive molar concentration"))
        if isinstance(node, ast.Call):
            fn = node.func.attr if isinstance(node.func, ast.Attribute) else \
                (node.func.id if isinstance(node.func, ast.Name) else "")
            if fn == "Diffusion" and len(node.args) >= 2 and (v := _num(node.args[1])) is not None:
                if not (1e-15 <= v <= 1e-8):
                    fix = ("a µm²/s value? multiply by 1e-12 → m²/s" if v > 1e-8
                           else "use m²/s, e.g. Ca ≈ 2e-10, a protein ≈ 1e-11")
                    out.append(("WARNING", node.lineno,
                                f"Diffusion constant {v:g} m²/s outside the cytosolic range ~1e-13–1e-9",
                                fix))
            if fn in LOADERS:
                for k in node.keywords:
                    if k.arg == "scale" and (v := _num(k.value)) is not None and v not in COMMON_SCALE:
                        out.append(("WARNING", node.lineno, f"unusual mesh scale={v:g}",
                                    "common scales: 1e-9 (nm→m), 1e-6 (µm→m), 1 (already m)"))
    return out


def validate_source(src):
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [("ERROR", e.lineno or 0, f"syntax error: {e.msg}", "fix the syntax error")]
    lines = src.splitlines()
    issues = (_import_checks(lines) + _ast_checks(tree) + _flow_checks(lines)
              + _reaction_checks(src) + _scale_checks(tree))
    return sorted(issues, key=lambda x: (x[1], x[0]))


def validate(path):
    return validate_source(pathlib.Path(path).read_text())


def _selftest():
    bad = ("from steps.model import *\n"
           "import steps.interface\n"            # interface after -> order error
           "A, Ca = Species.Create()\n"          # 'A' reserved
           "Diffusion(Ca, 100)\n"                # D in µm²/s, not m²/s
           "mesh = TetMesh.LoadGmsh('m.msh')\n"  # no scale=
           "for n in names:\n"
           "    roi = ROI.Create(t, name=n)\n"   # Create in loop
           "sim.cyt.Ca.Conc = 150\n"             # 150 M, not 150 µM
           "sim.run(1.0)\n")                     # run without newRun
    msgs = [(p + " " + f).lower() for _, _, p, f in validate_source(bad)]
    for needle in ("before", "reserved", "scale=", "loop", "newrun", "m²/s", "molar"):
        assert any(needle in m for m in msgs), f"self-test missed: {needle}"
    assert all(len(t) == 4 for t in validate_source(bad)), "issues must carry a fix"
    assert not validate_source("import steps.interface\nfrom steps.model import *\nx = 1\n")
    print("selftest OK")


def main(paths):
    if paths == ["--selftest"]:
        return _selftest()
    if not paths:
        sys.exit("usage: python validate_steps_script.py model.py [...]   (or --selftest)")
    total_err = 0
    for p in paths:
        issues = validate(p)
        errs = sum(1 for s, *_ in issues if s == "ERROR")
        total_err += errs
        print(f"\n{p} — {errs} error(s), {len(issues) - errs} warning(s)")
        for sev, line, problem, fix in issues:
            print(f"  {'✗' if sev == 'ERROR' else '▲'} {sev:7} L{line}: {problem}")
            if fix:
                print(f"        → fix: {fix}")
        if not issues:
            print("  ✓ no issues found")
    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
