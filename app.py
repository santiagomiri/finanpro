import os
import json
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, session, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import secrets
import logging

app = Flask(__name__)

_secret = os.environ.get("SECRET_KEY")
if not _secret:
    # Sin SECRET_KEY se genera una clave aleatoria (las sesiones se cierran al reiniciar).
    # Nunca usar una clave fija escrita en el código: el repositorio es público.
    logging.warning("SECRET_KEY no definida: usando clave temporal aleatoria.")
    _secret = secrets.token_hex(32)
app.secret_key = _secret
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",  # mitiga CSRF en peticiones POST desde otros sitios
)

# ─────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────

def get_db():
    db_path = os.environ.get("DATABASE_PATH", "database.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def crear_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            creado_en TEXT DEFAULT (date('now', '-5 hours'))
        );
        CREATE TABLE IF NOT EXISTS ingresos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            categoria TEXT,
            monto REAL NOT NULL,
            descripcion TEXT,
            fecha TEXT DEFAULT (date('now', '-5 hours')),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            categoria TEXT,
            monto REAL NOT NULL,
            descripcion TEXT,
            fecha TEXT DEFAULT (date('now', '-5 hours')),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
        CREATE TABLE IF NOT EXISTS gastos_fijos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            categoria TEXT,
            monto REAL NOT NULL,
            fecha_pago TEXT,
            estado TEXT DEFAULT 'Pendiente',
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
        CREATE TABLE IF NOT EXISTS presupuestos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            limite REAL NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
        CREATE TABLE IF NOT EXISTS metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            objetivo REAL NOT NULL,
            ahorro REAL DEFAULT 0,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
    """)
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# FILTRO DINERO
# ─────────────────────────────────────────

def format_money(value):
    try:
        return "{:,.0f}".format(float(value)).replace(",", ".")
    except:
        return value

app.jinja_env.filters['money'] = format_money

def limpiar_monto(raw):
    """Convierte un monto en formato colombiano a float.

    Ejemplos: "1.000.000" -> 1000000.0 | "10,50" -> 10.5 | "1.250,75" -> 1250.75
    El punto es separador de miles y la coma es separador decimal.
    Montos negativos o inválidos se devuelven como 0.0.
    """
    texto = str(raw or "").strip().replace("$", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = float(texto)
    except ValueError:
        return 0.0
    return round(valor, 2) if valor > 0 else 0.0

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    return decorated

# Tablas de movimientos según el tipo que envía el frontend.
# El calendario usa "ingreso"/"gasto"/"fijo" y el modal del día "Ingreso"/"Gasto"/"Fijo".
TABLAS_MOVIMIENTO = {
    "ingreso": {"tabla": "ingresos", "fecha": "fecha", "descripcion": "descripcion"},
    "gasto": {"tabla": "gastos", "fecha": "fecha", "descripcion": "descripcion"},
    "fijo": {"tabla": "gastos_fijos", "fecha": "fecha_pago", "descripcion": "nombre"},
}

def tabla_movimiento(tipo):
    """Devuelve la configuración de tabla para un tipo, o None si no es válido."""
    return TABLAS_MOVIMIENTO.get(str(tipo or "").strip().lower())

def hoy_colombia():
    from datetime import timedelta, timezone
    return datetime.now(timezone(timedelta(hours=-5))).date()

def sumar_meses(fecha, meses):
    """Suma meses a una fecha conservando el día (ajustado al último día del mes)."""
    import calendar
    mes_total = fecha.month - 1 + meses
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)

def renovar_gastos_fijos(conn, uid):
    """Los gastos fijos son mensuales: si un gasto 'Pagado' tiene su fecha de pago
    en un mes anterior al actual, se mueve al mes actual y vuelve a 'Pendiente'."""
    hoy = hoy_colombia()
    filas = conn.execute(
        "SELECT id, fecha_pago FROM gastos_fijos WHERE usuario_id=? AND estado='Pagado'", (uid,)
    ).fetchall()
    for f in filas:
        try:
            fecha = datetime.strptime(f["fecha_pago"], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        meses = (hoy.year - fecha.year) * 12 + (hoy.month - fecha.month)
        if meses > 0:
            nueva = sumar_meses(fecha, meses)
            conn.execute(
                "UPDATE gastos_fijos SET fecha_pago=?, estado='Pendiente' WHERE id=? AND usuario_id=?",
                (nueva.isoformat(), f["id"], uid),
            )
    conn.commit()

# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["nombre"] = user["nombre"]
            return redirect("/dashboard")
        error = "Correo o contraseña incorrectos"
    return render_template("login.html", error=error)

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not nombre or not email or not password:
            error = "Todos los campos son obligatorios"
        else:
            conn = get_db()
            existe = conn.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
            if existe:
                error = "Ya existe una cuenta con ese correo"
                conn.close()
            else:
                conn.execute(
                    "INSERT INTO usuarios (nombre, email, password) VALUES (?,?,?)",
                    (nombre, email, generate_password_hash(password))
                )
                conn.commit()
                conn.close()
                return redirect("/")
    return render_template("register.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ─────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    conn = get_db()
    renovar_gastos_fijos(conn, uid)

    ingresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM ingresos WHERE usuario_id=?", (uid,)).fetchone()[0]
    gastos   = conn.execute("SELECT COALESCE(SUM(monto),0) FROM gastos WHERE usuario_id=?", (uid,)).fetchone()[0]
    balance  = ingresos - gastos

    movimientos = conn.execute("""
        SELECT 'Ingreso' as tipo, monto, descripcion, fecha FROM ingresos WHERE usuario_id=?
        UNION ALL
        SELECT 'Gasto', monto, descripcion, fecha FROM gastos WHERE usuario_id=?
        ORDER BY fecha DESC LIMIT 50
    """, (uid, uid)).fetchall()

    alertas = conn.execute("""
        SELECT nombre, monto, fecha_pago FROM gastos_fijos
        WHERE usuario_id=? AND estado='Pendiente'
        ORDER BY fecha_pago ASC
    """, (uid,)).fetchall()

    conn.close()
    return render_template("dashboard.html",
        ingresos=ingresos, gastos=gastos, balance=balance,
        movimientos=movimientos, alertas=alertas,
        nombre=session.get("nombre","")
    )

@app.route("/add_ingreso", methods=["POST"])
@login_required
def add_ingreso():
    conn = get_db()
    conn.execute(
        "INSERT INTO ingresos (usuario_id, categoria, monto, descripcion, fecha) VALUES (?,?,?,?,date('now', '-5 hours'))",
        (session["user_id"], request.form["categoria"], limpiar_monto(request.form["monto"]), request.form["descripcion"])
    )
    conn.commit(); conn.close()
    return redirect("/dashboard")

@app.route("/add_gasto", methods=["POST"])
@login_required
def add_gasto():
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (usuario_id, categoria, monto, descripcion, fecha) VALUES (?,?,?,?,date('now', '-5 hours'))",
        (session["user_id"], request.form["categoria"], limpiar_monto(request.form["monto"]), request.form["descripcion"])
    )
    conn.commit(); conn.close()
    return redirect("/dashboard")

# ─────────────────────────────────────────
# GASTOS FIJOS
# ─────────────────────────────────────────

@app.route("/gastos_fijos")
@login_required
def gastos_fijos():
    uid = session["user_id"]
    conn = get_db()
    renovar_gastos_fijos(conn, uid)
    gastos = conn.execute("""
        SELECT id, nombre, categoria, monto, fecha_pago, estado
        FROM gastos_fijos WHERE usuario_id=? ORDER BY fecha_pago
    """, (uid,)).fetchall()
    conn.close()

    alertas = []
    for g in gastos:
        if g["estado"] == "Pendiente" and g["fecha_pago"]:
            try:
                dias = (datetime.strptime(g["fecha_pago"], "%Y-%m-%d") - datetime.now()).days
                if dias <= 3:
                    alertas.append((g["nombre"], dias))
            except:
                pass

    return render_template("gastos_fijos.html", gastos=gastos, alertas=alertas)

@app.route("/add_gasto_fijo", methods=["POST"])
@login_required
def add_gasto_fijo():
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos_fijos (usuario_id, nombre, categoria, monto, fecha_pago) VALUES (?,?,?,?,?)",
        (session["user_id"], request.form["nombre"], request.form["categoria"],
         limpiar_monto(request.form["monto"]), request.form["fecha_pago"])
    )
    conn.commit(); conn.close()
    return redirect("/gastos_fijos")

@app.route("/pagar_gasto_fijo", methods=["POST"])
@login_required
def pagar_gasto_fijo():
    conn = get_db()
    conn.execute("UPDATE gastos_fijos SET estado='Pagado' WHERE id=? AND usuario_id=?",
                 (request.form["id"], session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/gastos_fijos")

@app.route("/pendiente_gasto_fijo", methods=["POST"])
@login_required
def pendiente_gasto_fijo():
    conn = get_db()
    conn.execute("UPDATE gastos_fijos SET estado='Pendiente' WHERE id=? AND usuario_id=?",
                 (request.form["id"], session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/gastos_fijos")

@app.route("/eliminar_gasto_fijo", methods=["POST"])
@login_required
def eliminar_gasto_fijo():
    conn = get_db()
    conn.execute("DELETE FROM gastos_fijos WHERE id=? AND usuario_id=?",
                 (request.form["id"], session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/gastos_fijos")

# ─────────────────────────────────────────
# PRESUPUESTO
# ─────────────────────────────────────────

@app.route("/presupuesto")
@login_required
def presupuesto():
    uid = session["user_id"]
    conn = get_db()
    presupuestos = conn.execute("SELECT * FROM presupuestos WHERE usuario_id=?", (uid,)).fetchall()
    mes_actual = hoy_colombia().strftime("%Y-%m")  # el presupuesto es mensual
    data = []
    for p in presupuestos:
        gastado = conn.execute(
            """SELECT COALESCE(SUM(monto),0) FROM gastos
               WHERE usuario_id=? AND categoria=? AND strftime('%Y-%m', fecha)=?""",
            (uid, p["categoria"], mes_actual)
        ).fetchone()[0]
        data.append((p["id"], p["categoria"], p["limite"], gastado))
    conn.close()
    return render_template("presupuesto.html", data=data)

@app.route("/add_presupuesto", methods=["POST"])
@login_required
def add_presupuesto():
    conn = get_db()
    conn.execute("INSERT INTO presupuestos (usuario_id, categoria, limite) VALUES (?,?,?)",
                 (session["user_id"], request.form["categoria"], limpiar_monto(request.form["limite"])))
    conn.commit(); conn.close()
    return redirect("/presupuesto")

@app.route("/eliminar_presupuesto", methods=["POST"])
@login_required
def eliminar_presupuesto():
    conn = get_db()
    conn.execute("DELETE FROM presupuestos WHERE id=? AND usuario_id=?",
                 (request.form["id"], session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/presupuesto")

# ─────────────────────────────────────────
# METAS
# ─────────────────────────────────────────

@app.route("/metas")
@login_required
def metas():
    conn = get_db()
    metas_list = conn.execute("SELECT * FROM metas WHERE usuario_id=?", (session["user_id"],)).fetchall()
    conn.close()
    return render_template("metas.html", metas=metas_list)

@app.route("/crear_meta", methods=["POST"])
@login_required
def crear_meta():
    conn = get_db()
    conn.execute("INSERT INTO metas (usuario_id, nombre, objetivo) VALUES (?,?,?)",
                 (session["user_id"], request.form["nombre"], limpiar_monto(request.form["objetivo"])))
    conn.commit(); conn.close()
    return redirect("/metas")

@app.route("/ahorrar", methods=["POST"])
@login_required
def ahorrar():
    conn = get_db()
    conn.execute("UPDATE metas SET ahorro = ahorro + ? WHERE id=? AND usuario_id=?",
                 (limpiar_monto(request.form["monto"]), request.form["meta_id"], session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/metas")

@app.route("/eliminar_meta", methods=["POST"])
@login_required
def eliminar_meta():
    conn = get_db()
    conn.execute("DELETE FROM metas WHERE id=? AND usuario_id=?",
                 (request.form["id"], session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/metas")

# ─────────────────────────────────────────
# CALENDARIO
# ─────────────────────────────────────────

@app.route("/calendario")
@login_required
def calendario():
    return render_template("calendario.html")

@app.route("/eventos")
@login_required
def eventos():
    uid = session["user_id"]
    conn = get_db()
    renovar_gastos_fijos(conn, uid)
    result = []

    for i in conn.execute("SELECT id, monto, descripcion, fecha FROM ingresos WHERE usuario_id=?", (uid,)).fetchall():
        result.append({"id": str(i["id"]), "title": f"💰 ${format_money(i['monto'])}", "start": i["fecha"], "extendedProps": {"tipo": "ingreso"}})

    for g in conn.execute("SELECT id, monto, descripcion, fecha FROM gastos WHERE usuario_id=?", (uid,)).fetchall():
        result.append({"id": str(g["id"]), "title": f"💸 ${format_money(g['monto'])}", "start": g["fecha"], "extendedProps": {"tipo": "gasto"}})

    for f in conn.execute("SELECT id, nombre, monto, fecha_pago FROM gastos_fijos WHERE usuario_id=?", (uid,)).fetchall():
        if f["fecha_pago"]:
            result.append({"id": str(f["id"]), "title": f"📌 {f['nombre']}", "start": f["fecha_pago"], "extendedProps": {"tipo": "fijo"}})

    conn.close()
    return jsonify(result)

@app.route("/eventos_dia")
@login_required
def eventos_dia():
    uid = session["user_id"]
    fecha = request.args.get("fecha")
    conn = get_db()
    eventos = []

    for i in conn.execute("SELECT id, monto, descripcion FROM ingresos WHERE usuario_id=? AND fecha=?", (uid, fecha)).fetchall():
        eventos.append({"id": i["id"], "tipo": "Ingreso", "monto": float(i["monto"]), "descripcion": i["descripcion"] or ""})

    for g in conn.execute("SELECT id, monto, descripcion FROM gastos WHERE usuario_id=? AND fecha=?", (uid, fecha)).fetchall():
        eventos.append({"id": g["id"], "tipo": "Gasto", "monto": float(g["monto"]), "descripcion": g["descripcion"] or ""})

    for f in conn.execute("SELECT id, nombre, monto FROM gastos_fijos WHERE usuario_id=? AND fecha_pago=?", (uid, fecha)).fetchall():
        eventos.append({"id": f["id"], "tipo": "Fijo", "monto": float(f["monto"]), "descripcion": f["nombre"]})

    conn.close()
    return jsonify(eventos)

@app.route("/agregar_movimiento", methods=["POST"])
@login_required
def agregar_movimiento():
    uid = session["user_id"]
    tipo = request.form["tipo"]
    monto = limpiar_monto(request.form["monto"])
    desc = request.form["descripcion"]
    fecha = request.form["fecha"]
    conn = get_db()
    if tipo == "Ingreso":
        conn.execute("INSERT INTO ingresos (usuario_id, categoria, monto, descripcion, fecha) VALUES (?,?,?,?,?)",
                     (uid, "Otro", monto, desc, fecha))
    else:
        conn.execute("INSERT INTO gastos (usuario_id, categoria, monto, descripcion, fecha) VALUES (?,?,?,?,?)",
                     (uid, "Otro", monto, desc, fecha))
    conn.commit(); conn.close()
    return "ok"

@app.route("/editar_movimiento", methods=["POST"])
@login_required
def editar_movimiento():
    uid = session["user_id"]
    cfg = tabla_movimiento(request.form.get("tipo"))
    if not cfg:
        return "tipo inválido", 400
    monto = limpiar_monto(request.form.get("monto"))
    descripcion = request.form.get("descripcion", "").strip()
    conn = get_db()
    conn.execute(
        f"UPDATE {cfg['tabla']} SET monto=?, {cfg['descripcion']}=? WHERE id=? AND usuario_id=?",
        (monto, descripcion, request.form.get("id"), uid),
    )
    conn.commit(); conn.close()
    return "ok"

@app.route("/eliminar_movimiento", methods=["POST"])
@login_required
def eliminar_movimiento():
    uid = session["user_id"]
    cfg = tabla_movimiento(request.form.get("tipo"))
    if not cfg:
        return "tipo inválido", 400
    conn = get_db()
    conn.execute(f"DELETE FROM {cfg['tabla']} WHERE id=? AND usuario_id=?",
                 (request.form.get("id"), uid))
    conn.commit(); conn.close()
    return "ok"

@app.route("/mover_movimiento", methods=["POST"])
@login_required
def mover_movimiento():
    uid = session["user_id"]
    cfg = tabla_movimiento(request.form.get("tipo"))
    fecha = request.form.get("fecha", "")
    if not cfg:
        return "tipo inválido", 400
    try:
        datetime.strptime(fecha[:10], "%Y-%m-%d")
    except ValueError:
        return "fecha inválida", 400
    conn = get_db()
    conn.execute(f"UPDATE {cfg['tabla']} SET {cfg['fecha']}=? WHERE id=? AND usuario_id=?",
                 (fecha[:10], request.form.get("id"), uid))
    conn.commit(); conn.close()
    return "ok"

# ─────────────────────────────────────────
# ANÁLISIS
# ─────────────────────────────────────────

@app.route("/analisis")
@login_required
def analisis():
    uid = session["user_id"]
    conn = get_db()

    ingresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM ingresos WHERE usuario_id=?", (uid,)).fetchone()[0]
    gastos   = conn.execute("SELECT COALESCE(SUM(monto),0) FROM gastos WHERE usuario_id=?", (uid,)).fetchone()[0]
    balance  = ingresos - gastos

    categorias = conn.execute("""
        SELECT categoria, SUM(monto) as total FROM gastos WHERE usuario_id=?
        GROUP BY categoria ORDER BY total DESC
    """, (uid,)).fetchall()

    top_categoria = categorias[0]["categoria"] if categorias else None
    max_gasto = categorias[0]["total"] if categorias else 0

    porcentaje = (gastos / ingresos * 100) if ingresos > 0 else 0

    if porcentaje < 50: estado, color = "Excelente", "success"
    elif porcentaje < 80: estado, color = "Estable", "warning"
    else: estado, color = "Riesgoso", "danger"

    # Gasto total por mes (últimos 3 meses completos + mes actual)
    hoy = hoy_colombia()
    meses = [sumar_meses(hoy.replace(day=1), -i).strftime("%Y-%m") for i in range(3, -1, -1)]
    por_mes = dict(conn.execute("""
        SELECT strftime('%Y-%m', fecha), SUM(monto) FROM gastos
        WHERE usuario_id=? GROUP BY strftime('%Y-%m', fecha)""", (uid,)).fetchall())
    conn.close()
    cerrados = [por_mes.get(m, 0) for m in meses[:3]]
    con_datos = [v for v in cerrados if v > 0]

    # Predicción: promedio mensual de los últimos 3 meses con gastos
    prediccion = sum(con_datos) / len(con_datos) if con_datos else por_mes.get(meses[3], 0)

    # Tendencia: último mes cerrado vs. el anterior (±10 % se considera estable)
    tendencia = "Estable 📊"
    anterior, ultimo = cerrados[1], cerrados[2]
    if anterior > 0 and ultimo > 0:
        cambio = (ultimo - anterior) / anterior
        if cambio > 0.10: tendencia = "Subiendo 📈"
        elif cambio < -0.10: tendencia = "Bajando 📉"

    score = 100
    if porcentaje > 80: score -= 40
    elif porcentaje > 60: score -= 20
    if balance < 0: score -= 30
    if balance > 0: score += 10
    score = max(0, min(100, score))

    if score >= 80: nivel_score, color_score = "Excelente", "success"
    elif score >= 50: nivel_score, color_score = "Aceptable", "warning"
    else: nivel_score, color_score = "Crítico", "danger"

    return render_template("analisis.html",
        ingresos=ingresos, gastos=gastos, balance=balance,
        top_categoria=top_categoria, max_gasto=max_gasto,
        porcentaje=porcentaje, estado=estado, color=color,
        prediccion=prediccion, tendencia=tendencia,
        score=score, nivel_score=nivel_score, color_score=color_score
    )

# ─────────────────────────────────────────
# GRÁFICAS
# ─────────────────────────────────────────

@app.route("/graficas")
@login_required
def graficas():
    uid = session["user_id"]
    conn = get_db()

    ing_mes = dict(conn.execute("""
        SELECT strftime('%Y-%m', fecha), SUM(monto)
        FROM ingresos WHERE usuario_id=?
        GROUP BY strftime('%Y-%m', fecha) ORDER BY fecha
    """, (uid,)).fetchall())

    gas_mes = dict(conn.execute("""
        SELECT strftime('%Y-%m', fecha), SUM(monto)
        FROM gastos WHERE usuario_id=?
        GROUP BY strftime('%Y-%m', fecha) ORDER BY fecha
    """, (uid,)).fetchall())

    # Datos para gráfica de torta — gastos por categoría
    cat_gastos_rows = conn.execute("""
        SELECT categoria, SUM(monto) as total FROM gastos
        WHERE usuario_id=? GROUP BY categoria ORDER BY total DESC
    """, (uid,)).fetchall()

    # Datos para gráfica de torta — ingresos por categoría
    cat_ingresos_rows = conn.execute("""
        SELECT categoria, SUM(monto) as total FROM ingresos
        WHERE usuario_id=? GROUP BY categoria ORDER BY total DESC
    """, (uid,)).fetchall()

    conn.close()

    meses = sorted(set(ing_mes) | set(gas_mes))
    ingresos = [ing_mes.get(m, 0) for m in meses]
    gastos   = [gas_mes.get(m, 0) for m in meses]

    cat_gastos_labels  = [r["categoria"] or "Sin categoría" for r in cat_gastos_rows]
    cat_gastos_data    = [r["total"] for r in cat_gastos_rows]
    cat_ingresos_labels = [r["categoria"] or "Sin categoría" for r in cat_ingresos_rows]
    cat_ingresos_data   = [r["total"] for r in cat_ingresos_rows]

    return render_template("graficas.html",
        meses=meses, ingresos=ingresos, gastos=gastos,
        cat_gastos_labels=cat_gastos_labels, cat_gastos_data=cat_gastos_data,
        cat_ingresos_labels=cat_ingresos_labels, cat_ingresos_data=cat_ingresos_data
    )

# ─────────────────────────────────────────
# REPORTES PDF
# ─────────────────────────────────────────

@app.route("/reportes")
@login_required
def reportes():
    return render_template("reportes.html")

@app.route("/exportar_pdf", methods=["POST"])
@login_required
def exportar_pdf():
    import io
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable, KeepTogether)
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

    uid  = session["user_id"]
    nombre_usuario = session.get("nombre", "Usuario")
    modo = request.form.get("modo", "todo")

    # ── Construir filtro de fechas ──────────────────────────────
    filtro_i = ""
    filtro_g = ""
    params_i = [uid]
    params_g = [uid]

    if modo == "rango":
        desde = request.form.get("fecha_desde", "")
        hasta = request.form.get("fecha_hasta", "")
        if desde and hasta:
            filtro_i = " AND fecha BETWEEN ? AND ?"
            filtro_g = " AND fecha BETWEEN ? AND ?"
            params_i = [uid, desde, hasta]
            params_g = [uid, desde, hasta]
            periodo_label = f"{desde}  a  {hasta}"
        else:
            periodo_label = "Todos los períodos"
    elif modo == "dia":
        dia = request.form.get("fecha_dia", "")
        if dia:
            filtro_i = " AND fecha = ?"
            filtro_g = " AND fecha = ?"
            params_i = [uid, dia]
            params_g = [uid, dia]
            periodo_label = dia
        else:
            periodo_label = "Todos los períodos"
    else:
        periodo_label = "Todos los períodos"

    conn = get_db()
    ingresos_data = conn.execute(
        f"SELECT monto, descripcion, categoria, fecha FROM ingresos WHERE usuario_id=?{filtro_i} ORDER BY fecha DESC",
        params_i
    ).fetchall()
    gastos_data = conn.execute(
        f"SELECT monto, descripcion, categoria, fecha FROM gastos WHERE usuario_id=?{filtro_g} ORDER BY fecha DESC",
        params_g
    ).fetchall()

    # Gastos por categoría
    cat_gastos = conn.execute(
        f"SELECT categoria, SUM(monto) as total FROM gastos WHERE usuario_id=?{filtro_g} GROUP BY categoria ORDER BY total DESC",
        params_g
    ).fetchall()

    conn.close()

    total_i  = sum(d["monto"] for d in ingresos_data)
    total_g  = sum(d["monto"] for d in gastos_data)
    balance  = total_i - total_g
    ahorro_pct = round((balance / total_i * 100), 1) if total_i > 0 else 0

    # ── Colores de marca ───────────────────────────────────────
    AZUL_OSC  = colors.HexColor("#0f172a")
    AZUL_MED  = colors.HexColor("#1e293b")
    AZUL_BOR  = colors.HexColor("#334155")
    VERDE     = colors.HexColor("#22c55e")
    ROJO      = colors.HexColor("#ef4444")
    AZUL_ACT  = colors.HexColor("#3b82f6")
    GRIS_TEXT = colors.HexColor("#94a3b8")
    BLANCO    = colors.white
    AMARILLO  = colors.HexColor("#f59e0b")

    # ── Estilos ────────────────────────────────────────────────
    estilos = getSampleStyleSheet()

    def estilo(name, **kw):
        return ParagraphStyle(name, **kw)

    st_titulo = estilo("Titulo",
        fontSize=22, textColor=BLANCO, fontName="Helvetica-Bold",
        alignment=TA_LEFT, spaceAfter=2)
    st_sub = estilo("Sub",
        fontSize=10, textColor=GRIS_TEXT, fontName="Helvetica",
        alignment=TA_LEFT, spaceAfter=0)
    st_section = estilo("Section",
        fontSize=12, textColor=BLANCO, fontName="Helvetica-Bold",
        spaceBefore=14, spaceAfter=8)
    st_normal = estilo("Norm",
        fontSize=9, textColor=GRIS_TEXT, fontName="Helvetica", spaceAfter=3)
    st_center = estilo("Cent",
        fontSize=9, textColor=GRIS_TEXT, fontName="Helvetica",
        alignment=TA_CENTER)
    st_num_verde = estilo("NumV",
        fontSize=18, textColor=VERDE, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceAfter=2)
    st_num_rojo  = estilo("NumR",
        fontSize=18, textColor=ROJO, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceAfter=2)
    st_num_azul  = estilo("NumA",
        fontSize=18, textColor=AZUL_ACT, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceAfter=2)
    st_label = estilo("Label",
        fontSize=8, textColor=GRIS_TEXT, fontName="Helvetica",
        alignment=TA_CENTER, spaceAfter=0)
    st_msg = estilo("Msg",
        fontSize=10, textColor=BLANCO, fontName="Helvetica-Bold",
        alignment=TA_CENTER)

    # ── Helpers ────────────────────────────────────────────────
    def hr(color=AZUL_BOR, thickness=0.5):
        return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=10, spaceBefore=4)

    W = A4[0] - 3*cm   # ancho útil de tabla full

    # ── Tabla resumen (3 columnas) ──────────────────────────────
    def tabla_resumen():
        bal_color = VERDE if balance >= 0 else ROJO
        bal_st = estilo("BalSt", fontSize=18, textColor=bal_color,
                        fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=2)
        data = [[
            Paragraph("INGRESOS",   st_label),
            Paragraph("GASTOS",     st_label),
            Paragraph("BALANCE",    st_label),
        ],[
            Paragraph(f"$ {format_money(total_i)}", st_num_verde),
            Paragraph(f"$ {format_money(total_g)}", st_num_rojo),
            Paragraph(f"$ {format_money(balance)}",  bal_st),
        ]]
        col = W / 3
        t = Table(data, colWidths=[col, col, col])
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,-1), AZUL_MED),
            ("BACKGROUND",  (0,0), (0,-1),  colors.HexColor("#0d2818")),
            ("BACKGROUND",  (1,0), (1,-1),  colors.HexColor("#2d0f0f")),
            ("BACKGROUND",  (2,0), (2,-1),  colors.HexColor("#0d1e3a")),
            ("ROUNDEDCORNERS", [8]),
            ("TOPPADDING",  (0,0), (-1,-1), 14),
            ("BOTTOMPADDING",(0,0),(-1,-1), 14),
            ("LINEAFTER",   (0,0), (1,-1),  0.5, AZUL_BOR),
            ("ALIGN",       (0,0), (-1,-1), "CENTER"),
            ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ]))
        return t

    # ── Tabla de ahorro ────────────────────────────────────────
    def tabla_ahorro():
        if total_i == 0:
            return Spacer(1, 0)
        color_pct = VERDE if ahorro_pct >= 0 else ROJO
        st_pct = estilo("Pct", fontSize=13, textColor=color_pct,
                        fontName="Helvetica-Bold", alignment=TA_CENTER)
        msg_txt = "Excelente manejo financiero" if ahorro_pct >= 20 else \
                  ("Buen balance" if ahorro_pct >= 0 else "Gastos superan ingresos")
        data = [[
            Paragraph("TASA DE AHORRO", st_label),
            Paragraph("ESTADO", st_label),
        ],[
            Paragraph(f"{ahorro_pct}%", st_pct),
            Paragraph(msg_txt, st_msg),
        ]]
        t = Table(data, colWidths=[W*0.35, W*0.65])
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,-1), AZUL_MED),
            ("TOPPADDING",  (0,0), (-1,-1), 10),
            ("BOTTOMPADDING",(0,0),(-1,-1), 10),
            ("LINEAFTER",   (0,0), (0,-1),  0.5, AZUL_BOR),
            ("ALIGN",       (0,0), (-1,-1), "CENTER"),
            ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
            ("ROUNDEDCORNERS", [6]),
        ]))
        return t

    # ── Tabla de movimientos ────────────────────────────────────
    def tabla_movimientos(data, tipo):
        if not data:
            return Paragraph(f"No hay {tipo.lower()} en el período seleccionado.", st_normal)
        col_cat  = W * 0.20
        col_desc = W * 0.38
        col_mon  = W * 0.22
        col_fec  = W * 0.20
        header_color = colors.HexColor("#0d2818") if tipo == "Ingresos" else colors.HexColor("#2d0f0f")
        accent = VERDE if tipo == "Ingresos" else ROJO
        st_h = estilo(f"TH{tipo}", fontSize=8, textColor=BLANCO,
                      fontName="Helvetica-Bold", alignment=TA_CENTER)
        st_td = estilo(f"TD{tipo}", fontSize=8, textColor=GRIS_TEXT, fontName="Helvetica")
        st_td_r = estilo(f"TDR{tipo}", fontSize=8, textColor=accent,
                         fontName="Helvetica-Bold", alignment=TA_RIGHT)
        rows = [[
            Paragraph("CATEGORÍA", st_h),
            Paragraph("DESCRIPCIÓN", st_h),
            Paragraph("MONTO", st_h),
            Paragraph("FECHA", st_h),
        ]]
        for i, d in enumerate(data):
            rows.append([
                Paragraph(d["categoria"] or "—", st_td),
                Paragraph(d["descripcion"] or "—", st_td),
                Paragraph(f"$ {format_money(d['monto'])}", st_td_r),
                Paragraph(d["fecha"], st_td),
            ])
        style = [
            ("BACKGROUND",    (0,0), (-1,0),  header_color),
            ("BACKGROUND",    (0,1), (-1,-1), AZUL_OSC),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [AZUL_OSC, AZUL_MED]),
            ("LINEBELOW",     (0,0), (-1,0),  1, accent),
            ("LINEBELOW",     (0,1), (-1,-2), 0.3, AZUL_BOR),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]
        t = Table(rows, colWidths=[col_cat, col_desc, col_mon, col_fec], repeatRows=1)
        t.setStyle(TableStyle(style))
        return t

    # ── Tabla categorías ────────────────────────────────────────
    def tabla_categorias():
        if not cat_gastos:
            return Spacer(1, 0)
        st_h = estilo("CatH", fontSize=8, textColor=BLANCO, fontName="Helvetica-Bold")
        st_td = estilo("CatTD", fontSize=8, textColor=GRIS_TEXT, fontName="Helvetica")
        st_mon = estilo("CatMon", fontSize=8, textColor=ROJO, fontName="Helvetica-Bold", alignment=TA_RIGHT)
        st_pct_td = estilo("CatPct", fontSize=8, textColor=AMARILLO,
                           fontName="Helvetica-Bold", alignment=TA_RIGHT)
        rows = [[
            Paragraph("CATEGORÍA", st_h),
            Paragraph("TOTAL", st_h),
            Paragraph("% DEL TOTAL", st_h),
        ]]
        for c in cat_gastos:
            pct = round(c["total"] / total_g * 100, 1) if total_g > 0 else 0
            rows.append([
                Paragraph(c["categoria"] or "Sin categoría", st_td),
                Paragraph(f"$ {format_money(c['total'])}", st_mon),
                Paragraph(f"{pct}%", st_pct_td),
            ])
        t = Table(rows, colWidths=[W*0.50, W*0.28, W*0.22])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#2d0f0f")),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [AZUL_OSC, AZUL_MED]),
            ("LINEBELOW",     (0,0), (-1,0),  1, ROJO),
            ("LINEBELOW",     (0,1), (-1,-2), 0.3, AZUL_BOR),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]))
        return t

    # ── Encabezado de página ────────────────────────────────────
    def header_table():
        st_brand = estilo("Brand", fontSize=24, textColor=BLANCO,
                          fontName="Helvetica-Bold", alignment=TA_LEFT)
        st_meta  = estilo("Meta",  fontSize=8,  textColor=GRIS_TEXT,
                          fontName="Helvetica", alignment=TA_RIGHT)
        generado = datetime.now().strftime("%d/%m/%Y %H:%M")
        meta_txt = (f"Generado: {generado}<br/>"
                    f"Usuario: {nombre_usuario}<br/>"
                    f"Período: {periodo_label}")
        data = [[
            Paragraph("FinanPro", st_brand),
            Paragraph(meta_txt, st_meta),
        ]]
        t = Table(data, colWidths=[W*0.5, W*0.5])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), AZUL_OSC),
            ("TOPPADDING",    (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]))
        return t

    # ── Armar documento ────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )

    content = []

    # Encabezado
    content.append(header_table())
    content.append(Spacer(1, 14))
    content.append(hr(AZUL_ACT, 1.5))

    # Resumen
    content.append(Paragraph("Resumen del Período", st_section))
    content.append(tabla_resumen())
    content.append(Spacer(1, 10))
    content.append(tabla_ahorro())
    content.append(Spacer(1, 14))
    content.append(hr())

    # Gastos por categoría
    if cat_gastos:
        content.append(Paragraph("Gastos por Categoría", st_section))
        content.append(tabla_categorias())
        content.append(Spacer(1, 14))
        content.append(hr())

    # Detalle ingresos
    content.append(Paragraph(f"Ingresos  ({len(ingresos_data)} registros)", st_section))
    content.append(tabla_movimientos(list(ingresos_data), "Ingresos"))
    content.append(Spacer(1, 14))
    content.append(hr())

    # Detalle gastos
    content.append(Paragraph(f"Gastos  ({len(gastos_data)} registros)", st_section))
    content.append(tabla_movimientos(list(gastos_data), "Gastos"))

    doc.build(content)
    buf.seek(0)

    nombre_archivo = f"reporte_finanpro_{periodo_label.replace(' ', '').replace('→','_')}.pdf"
    return send_file(buf, as_attachment=True,
                     download_name=nombre_archivo, mimetype="application/pdf")

# ─────────────────────────────────────────
# INIT
# ─────────────────────────────────────────

with app.app_context():
    crear_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
