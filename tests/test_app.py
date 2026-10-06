"""Pruebas de regresión de FinanPro. Ejecutar con:  pip install pytest && pytest"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SECRET_KEY", "test")
    import app as modulo
    modulo = importlib.reload(modulo)
    cliente = modulo.app.test_client()
    cliente.post("/register", data={"nombre": "Test", "email": "t@t.co", "password": "x"})
    cliente.post("/", data={"email": "t@t.co", "password": "x"})
    return modulo, cliente, modulo.get_db()


def test_eliminar_gasto_fijo_no_borra_gastos(ctx):
    _, c, db = ctx
    c.post("/add_gasto", data={"categoria": "Comida", "monto": "50.000", "descripcion": "Mercado"})
    c.post("/add_gasto_fijo", data={"nombre": "Arriendo", "categoria": "Hogar",
                                    "monto": "900.000", "fecha_pago": "2026-10-30"})
    c.post("/eliminar_movimiento", data={"id": 1, "tipo": "Fijo"})
    assert db.execute("SELECT COUNT(*) FROM gastos_fijos").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM gastos").fetchone()[0] == 1


def test_mover_y_editar_gasto_fijo(ctx):
    _, c, db = ctx
    c.post("/add_gasto_fijo", data={"nombre": "Internet", "categoria": "Hogar",
                                    "monto": "100.000", "fecha_pago": "2026-10-15"})
    c.post("/mover_movimiento", data={"id": 1, "tipo": "fijo", "fecha": "2026-10-20"})
    c.post("/editar_movimiento", data={"id": 1, "tipo": "Fijo", "monto": "120000",
                                       "descripcion": "Internet fibra"})
    fila = db.execute("SELECT nombre, monto, fecha_pago FROM gastos_fijos").fetchone()
    assert tuple(fila) == ("Internet fibra", 120000.0, "2026-10-20")


def test_tipo_invalido(ctx):
    _, c, _ = ctx
    assert c.post("/eliminar_movimiento", data={"id": 1, "tipo": "otro"}).status_code == 400


def test_presupuesto_solo_mes_actual(ctx):
    m, c, db = ctx
    mes = m.hoy_colombia().strftime("%Y-%m")
    db.execute("INSERT INTO gastos (usuario_id, categoria, monto, fecha) VALUES (1,'Comida',400000,'2000-01-01')")
    db.execute("INSERT INTO gastos (usuario_id, categoria, monto, fecha) VALUES (1,'Comida',50000,?)", (mes + "-01",))
    db.commit()
    c.post("/add_presupuesto", data={"categoria": "Comida", "limite": "300.000"})
    html = c.get("/presupuesto").data.decode()
    assert "450.000" not in html and "50.000" in html


@pytest.mark.parametrize("entrada,esperado", [
    ("1.000.000", 1_000_000), ("10,50", 10.5), ("1.250,75", 1250.75),
    ("$ 20.000", 20_000), ("-5", 0), ("abc", 0), (None, 0),
])
def test_limpiar_monto(ctx, entrada, esperado):
    m, _, _ = ctx
    assert m.limpiar_monto(entrada) == esperado


def test_gasto_fijo_pagado_se_renueva_cada_mes(ctx):
    m, c, db = ctx
    hoy = m.hoy_colombia()
    viejo = m.sumar_meses(hoy.replace(day=28), -2)
    db.execute("INSERT INTO gastos_fijos (usuario_id, nombre, monto, fecha_pago, estado) "
               "VALUES (1,'Gym',80000,?,'Pagado')", (viejo.isoformat(),))
    db.commit()
    c.get("/gastos_fijos")
    fecha, estado = db.execute("SELECT fecha_pago, estado FROM gastos_fijos").fetchone()
    assert estado == "Pendiente" and fecha.startswith(hoy.strftime("%Y-%m"))


def test_sumar_meses_fin_de_mes(ctx):
    m, _, _ = ctx
    assert m.sumar_meses(m.date(2026, 1, 31), 1) == m.date(2026, 2, 28)


@pytest.mark.parametrize("ruta", ["/dashboard", "/gastos_fijos", "/presupuesto", "/metas",
                                  "/calendario", "/eventos", "/analisis", "/graficas", "/reportes"])
def test_paginas_cargan(ctx, ruta):
    _, c, _ = ctx
    assert c.get(ruta).status_code == 200
