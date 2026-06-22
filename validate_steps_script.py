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

    python validate_steps_script.py model.py [more.py ... | folder/]   # or --selftest

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
            # introspection reads the call's FIRST physical line — it needs
            # `name = X.Create(` there. Arguments may wrap to later lines (fine); only
            # flag when the assignment and the `.Create(` start on different lines.
            same_start = node.value.lineno == node.lineno
            if ok_targets and not in_loop_or_comp(node.value):
                good.add(node.value)
                if not same_start:
                    out.append(("WARNING", node.lineno,
                                "`.Create()` starts on a different line from its assignment",
                                f"put `name = {cls}.Create(` on one line (args may then wrap)"))
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
            # scale is the 2nd positional arg (LoadGmsh(path, scale, ...)) or scale=kw
            if not any(k.arg == "scale" for k in node.keywords) and len(node.args) < 2:
                out.append(("WARNING", node.lineno, f"{node.func.attr}() has no scale",
                            "pass scale (2nd arg or scale=) so coords become metres (1e-9 nm, 1e-6 µm)"))
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
                    elif v < 0:
                        out.append(("WARNING", node.lineno, f"Conc {v:g} M is negative",
                                    "set a non-negative molar concentration (0 clears the species)"))
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


def _comprehension_checks(tree):
    """Catch the loop-variable-ordering trap: a comprehension whose FIRST iterable
    uses a name bound by a LATER `for`. Python evaluates the first iterable eagerly in
    the enclosing scope, so that name is a stale value — e.g.
    `TetList(t for t in mito.tets for mito in mitos)` reads only the last `mito`.
    A real, silent bug found in a STEPS model (mitochondrial-Ca recording)."""
    out = []
    comps = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)
    for node in ast.walk(tree):
        if isinstance(node, comps) and len(node.generators) >= 2:
            later = {n.id for g in node.generators[1:]
                     for n in ast.walk(g.target) if isinstance(n, ast.Name)}
            first_iter = {n.id for n in ast.walk(node.generators[0].iter)
                          if isinstance(n, ast.Name)}
            clash = sorted(first_iter & later)
            if clash:
                out.append(("WARNING", node.lineno,
                            f"comprehension's first iterable uses {clash}, which a later "
                            "`for` binds — it reads a stale value, not each element",
                            "reorder the clauses so the variable is bound before use: "
                            "`[... for outer in seq for inner in outer...]`"))
    return out


def _loop_checks(tree):
    """A `for X in ...:` whose body never uses X *and* shadows it with an inner
    comprehension that rebinds X — the body recomputes the same result every
    iteration (O(n²) and a stray loop). Found in real STEPS geometry setup."""
    out = []
    comps = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.For) and isinstance(node.target, ast.Name)):
            continue
        t = node.target.id
        shadowed = [c for stmt in node.body for c in ast.walk(stmt)
                    if isinstance(c, comps)
                    and any(isinstance(g.target, ast.Name) and g.target.id == t
                            for g in c.generators)]
        if not shadowed:
            continue
        # is t Loaded anywhere in the body OUTSIDE a comprehension that rebinds it?
        used = [False]
        def rec(n):
            if isinstance(n, comps) and any(isinstance(g.target, ast.Name)
                                            and g.target.id == t for g in n.generators):
                return  # t is a separate variable inside this comprehension — skip
            if isinstance(n, ast.Name) and n.id == t and isinstance(n.ctx, ast.Load):
                used[0] = True
            for c in ast.iter_child_nodes(n):
                rec(c)
        for stmt in node.body:
            rec(stmt)
        if not used[0]:
            out.append(("WARNING", node.lineno,
                        f"loop variable '{t}' is unused in the body and shadowed by an inner "
                        "comprehension — the loop recomputes the same result each iteration",
                        "drop the stray `for` loop (compute the comprehension once), or use the "
                        "loop variable"))
    return out


def _geometry_checks(tree):
    """Exact float (in)equality on mesh geometry (`.center`, `.bbox`, `.Pos`) rarely
    matches — a classic STEPS trap when picking boundary tris/tets. Use a tolerance or
    a half-space test (`<=`/`>=`)."""
    out, GEO = [], {"center", "bbox", "Pos"}
    eq_ops = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)

    def is_geo_coord(o):
        # o is *directly* a coordinate access (tri.center.y, m.bbox.max.y, v.Pos) —
        # NOT a reduction like len(x.center) or norm(a-b), which compare scalars.
        while isinstance(o, ast.Attribute):
            if o.attr in GEO:
                return True
            o = o.value
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(isinstance(o, eq_ops) for o in node.ops):
            operands = [node.left, *node.comparators]
            if any(is_geo_coord(o) for o in operands):
                out.append(("WARNING", node.lineno,
                            "exact float (in)equality on mesh geometry (center/bbox/Pos) "
                            "rarely matches — boundary selection silently misses",
                            "use a tolerance `abs(a-b) < eps` or a half-space test `<=`/`>=`"))
    return out


def _const_num(node):
    """Safe-eval a purely numeric expression AST (literals + + - * / ** and unary -).
    Real models write rates as e.g. `K_PP2A = 0.6 / 7.8e-6` — resolve those."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _const_num(node.operand)
        return None if v is None else -v
    if isinstance(node, ast.BinOp):
        a, b = _const_num(node.left), _const_num(node.right)
        if a is None or b is None:
            return None
        op = node.op
        if isinstance(op, ast.Add):  return a + b
        if isinstance(op, ast.Sub):  return a - b
        if isinstance(op, ast.Mult): return a * b
        if isinstance(op, ast.Div):  return a / b if b else None
        if isinstance(op, ast.Pow):  return a ** b
    return None


def _unquote(idx):
    """`'bind'` → `bind`; a variable/f-string index (`name`, `f'grip_{z}'`) is left as-is."""
    s = idx.strip()
    m = re.fullmatch(r"['\"](\w+)['\"]", s)
    return m.group(1) if m else s


def _comment_on(lines, end_lineno):
    raw = lines[end_lineno - 1] if 0 < end_lineno <= len(lines) else ""
    return raw.split("#", 1)[1].strip() if "#" in raw else ""


def extract_params(src):
    """Pull the model's kinetic content into a structured table so it can be compared
    against a publication / the literature (see SKILL.md → "Validate against the
    literature"). Surfaces what to check; does not run the model. Returns a dict of
    lists: schemes, rates, diffusions, inits, constants.

    Real STEPS models are data-driven — reactions built in helpers from *named*
    constants (`KON_GRIP = 5.5e6`) and dicts (`CONC = {...}`), not literal
    `r['x'].K = 1e6` lines. So the workhorse is `constants`: module-level numeric
    assignments (incl. tuple-unpacking and dict literals) with their inline comments,
    which is where the parameters — and often their citations — actually live."""
    lines = src.splitlines()
    schemes, rates, diffs, inits = [], [], [], []
    for i, raw in enumerate(lines, 1):
        code = raw.split("#", 1)[0]
        comment = raw.split("#", 1)[1].strip() if "#" in raw else ""
        # reaction scheme: `... <r[..]> ...` / `... >r[..]> ...` (any index, then `>`)
        if (m := re.search(r"r\[([^\]]+)\]\s*>", code)):
            schemes.append((i, _unquote(m.group(1)), code.strip()))
        # rate constant assignment: r[..].K = <expr>  (index may be a variable/f-string)
        if (m := re.search(r"\br\[([^\]]+)\]\s*\.\s*K\b\s*=\s*(.+)", code)):
            rates.append((i, _unquote(m.group(1)), m.group(2).strip(), comment))
        # diffusion constant: Diffusion(Spec, D, ...)
        if (m := re.search(r"\bDiffusion\(\s*(\w+)\s*,\s*([^,)]+?)\s*[,)]", code)):
            diffs.append((i, m.group(1), m.group(2).strip(), comment))
        # initial condition: <handle>.<...>.(Conc|Count) = <expr>  (handle may be aliased)
        if (m := re.search(r"\b([A-Za-z_]\w*(?:\.\w+)+)\.(Conc|Count)\s*=\s*(.+)", code)):
            inits.append((i, m.group(1), m.group(2), m.group(3).strip()))

    constants = []
    try:
        tree = ast.parse(src)
        for node in tree.body:                       # module level only
            if not isinstance(node, ast.Assign):
                continue
            note = _comment_on(lines, node.end_lineno or node.lineno)
            val = node.value
            # dict literal: CONC = {'GRIP': 1.1e-6, ...}
            if isinstance(val, ast.Dict) and isinstance(node.targets[0], ast.Name):
                dname = node.targets[0].id
                for k, v in zip(val.keys, val.values):
                    num = _const_num(v)
                    key = k.value if isinstance(k, ast.Constant) else "?"
                    if num is not None or isinstance(k, ast.Constant):
                        constants.append((node.lineno, f"{dname}['{key}']", num, note))
                continue
            names = node.targets[0]
            # tuple unpack: KON_GRIP, KOFF_GRIP = 5.5e6, 0.3
            if isinstance(names, ast.Tuple) and isinstance(val, ast.Tuple) \
                    and len(names.elts) == len(val.elts):
                for n, v in zip(names.elts, val.elts):
                    num = _const_num(v)
                    if isinstance(n, ast.Name) and num is not None:
                        constants.append((node.lineno, n.id, num, note))
            elif isinstance(names, ast.Name) and (num := _const_num(val)) is not None:
                constants.append((node.lineno, names.id, num, note))
    except SyntaxError:
        pass
    return {"schemes": schemes, "rates": rates, "diffusions": diffs,
            "inits": inits, "constants": constants}


def print_params(path):
    p = extract_params(pathlib.Path(path).read_text())
    print(f"\n{path} — extracted kinetic parameters (compare against the source/literature)")
    if p["constants"]:
        print("\n  Numeric constants (rates/concentrations live here in data-driven models):")
        for i, name, num, note in p["constants"]:
            shown = f"{num:g}" if num is not None else "?"
            print(f"    L{i:<4} {name:<22} = {shown}" + (f"   # {note}" if note else ""))
    if p["schemes"]:
        print("\n  Reaction schemes:")
        for i, key, txt in p["schemes"]:
            print(f"    L{i:<4} [{key}]  {txt}")
    if p["rates"]:
        print("\n  Rate-constant assignments (r[..].K) — 1/s (1st order), 1/(M·s) (2nd order):")
        for i, key, val, note in p["rates"]:
            print(f"    L{i:<4} {key:<18} = {val}" + (f"   # {note}" if note else ""))
    if p["diffusions"]:
        print("\n  Diffusion constants (m²/s):")
        for i, spec, d, note in p["diffusions"]:
            print(f"    L{i:<4} {spec:<14} D = {d}" + (f"   # {note}" if note else ""))
    if p["inits"]:
        print("\n  Initial conditions (Conc = molar / Count = molecules):")
        for i, sp, kind, val in p["inits"]:
            print(f"    L{i:<4} {sp}.{kind} = {val}")
    if not any(p.values()):
        print("  (no reactions, rates, diffusions, constants, or initial conditions found)")


def validate_source(src):
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [("ERROR", e.lineno or 0, f"syntax error: {e.msg}", "fix the syntax error")]
    lines = src.splitlines()
    issues = (_import_checks(lines) + _ast_checks(tree) + _flow_checks(lines)
              + _reaction_checks(src) + _scale_checks(tree) + _comprehension_checks(tree)
              + _loop_checks(tree) + _geometry_checks(tree))
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
    # regression: wrapped Create() args and Conc = 0 are valid, not warnings
    ok = ("import steps.interface\nfrom steps.model import *\n"
          "rate = VDepRate.Create(\n    lambda V: V)\n"   # args wrap to next line
          "mesh = TetMesh.LoadGmsh('m.msh', 1e-6)\n"      # scale given positionally, not scale=
          "sim.cyto.Fluo.Conc = 0.0\n")                   # zeroing a species is fine
    assert validate_source(ok) == [], f"false positive(s): {validate_source(ok)}"
    # comprehension loop-variable-ordering trap (the mito_tet_lst bug)
    comp = validate_source("ts = TetList(t for t in m.tets for m in mitos)\n")
    assert any("stale value" in p for _, _, p, _ in comp), "comprehension-order check"
    # stray loop: unused target shadowed by an inner comprehension
    loop = validate_source("for tri in memb:\n    a = [tri for tri in memb if tri.x]\n")
    assert any("recomputes the same result" in p for _, _, p, _ in loop), "stray-loop check"
    # geometry float equality
    geo = validate_source("xs = [t for t in surf if t.center.y not in ends]\n")
    assert any("rarely matches" in p for _, _, p, _ in geo), "geometry-equality check"
    # half-space test must NOT trip the geometry check
    assert not any("rarely matches" in p for _, _, p, _ in
                   validate_source("xs = [t for t in surf if t.center.y <= 0]\n")), "geo false-positive"
    # --params extraction picks up scheme, rate, diffusion, and initial condition
    pp = extract_params("A + B <r['bind']> C\nr['bind'].K = 1e6, 0.7  # Smith 2020\n"
                        "Diffusion(Ca, 2e-10)\nsim.cyt.Ca.Conc = 150e-6\n")
    assert [s[1] for s in pp["schemes"]] == ["bind"], pp["schemes"]
    assert pp["rates"][0][1:3] == ("bind", "1e6, 0.7") and pp["rates"][0][3] == "Smith 2020"
    assert pp["diffusions"][0][1:3] == ("Ca", "2e-10")
    assert pp["inits"][0][1:4] == ("sim.cyt.Ca", "Conc", "150e-6")
    # data-driven model (the real case): named constants, tuple-unpack, evaluated
    # arithmetic, a CONC dict, variable r[name], and an aliased (`c.`) init handle
    dd = extract_params(
        "KON_GRIP, KOFF_GRIP = 5.5e6, 0.3   # Gallimore 2016, Table 1\n"
        "K_PP2A = 0.6 / 7.8e-6\n"
        "CONC = {'GRIP': 1.1e-6, 'PICK1': 0.66e-6}   # basal (M)\n"
        "FREE = ['GRIP', 'PICK1']\n"                  # non-numeric list: must be ignored
        "def rev(name, l, rr, kf, kb):\n    l <r[name]> rr\n    r[name].K = kf, kb\n"
        "c = sim.comp\nc.PKCa.Count = 0\n")
    cd = {name: num for _, name, num, _ in dd["constants"]}
    assert cd["KON_GRIP"] == 5.5e6 and cd["KOFF_GRIP"] == 0.3, dd["constants"]
    assert abs(cd["K_PP2A"] - 0.6 / 7.8e-6) < 1, cd            # arithmetic evaluated
    assert cd["CONC['GRIP']"] == 1.1e-6 and cd["CONC['PICK1']"] == 0.66e-6
    assert "FREE" not in cd, "non-numeric list leaked into constants"
    assert any(n == "Gallimore 2016, Table 1" for *_, n in dd["constants"]), "comment lost"
    assert [s[1] for s in dd["schemes"]] == ["name"], dd["schemes"]   # variable index
    assert dd["inits"][0][1:4] == ("c.PKCa", "Count", "0"), dd["inits"]  # aliased handle
    # directory argument expands to the .py files inside, skipping __pycache__
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "model.py"), "w").close()
        os.makedirs(os.path.join(d, "__pycache__"))
        open(os.path.join(d, "__pycache__", "cached.py"), "w").close()
        ex = _expand([d, "literal.py"])
        assert ex == [os.path.join(d, "model.py"), "literal.py"], ex
    print("selftest OK")


def _expand(paths):
    """Expand any directory argument to the .py files inside it (recursive, skipping
    __pycache__), so the user can pass a model folder instead of every filename."""
    out = []
    for p in paths:
        pp = pathlib.Path(p)
        if pp.is_dir():
            files = sorted(str(f) for f in pp.rglob("*.py")
                           if "__pycache__" not in f.parts)
            if not files:
                sys.exit(f"no .py files found in directory: {p}")
            out.extend(files)
        else:
            out.append(p)
    return out


def main(paths):
    if paths == ["--selftest"]:
        return _selftest()
    if paths and paths[0] == "--params":
        if len(paths) < 2:
            sys.exit("usage: python validate_steps_script.py --params model.py [...]")
        for p in _expand(paths[1:]):
            print_params(p)
        return
    if not paths:
        sys.exit("usage: python validate_steps_script.py model.py [...]   "
                 "(or a folder, --params model.py, or --selftest)")
    total_err = 0
    for p in _expand(paths):
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
