# FinanPro

Aplicación web de finanzas personales: registra ingresos y gastos, controla pagos fijos y presupuestos mensuales, sigue metas de ahorro y genera análisis, gráficas y reportes en PDF.

Construida con **Python y Flask**, con base de datos **SQLite** y pruebas automáticas con **pytest**. Pensada para el contexto colombiano: montos en formato local (`1.250.000,50`) y fechas en hora de Colombia (UTC−5).

---

## Funciones

**Cuentas de usuario**
- Registro e inicio de sesión; contraseñas almacenadas con hash (Werkzeug).
- Cada usuario ve y modifica únicamente sus propios datos.

**Panel principal**
- Totales de ingresos, gastos y balance.
- Últimos 50 movimientos y alertas de pagos fijos pendientes.
- Registro rápido de ingresos y gastos por categoría.

**Gastos fijos**
- Pagos recurrentes con fecha y estado (pendiente / pagado).
- Aviso cuando un pago vence en 3 días o menos.
- Renovación mensual automática: al cambiar de mes, un pago marcado como pagado vuelve a quedar pendiente con la nueva fecha.

**Presupuesto mensual**
- Límite de gasto por categoría, comparado con lo gastado en el mes actual.

**Metas de ahorro**
- Metas con valor objetivo y abonos progresivos.

**Calendario**
- Ingresos, gastos y pagos fijos en un calendario interactivo (FullCalendar).
- Desde el calendario se agregan, editan y eliminan movimientos, y se arrastran a otra fecha.

**Análisis**
- Porcentaje de los ingresos que se va en gastos y categoría de mayor gasto.
- Proyección del gasto mensual (promedio de los últimos tres meses con gastos).
- Tendencia del último mes frente al anterior y un puntaje de salud financiera de 0 a 100.

**Gráficas**
- Ingresos vs. gastos por mes y distribución por categoría (Chart.js).

**Reportes PDF**
- Reporte descargable de todo el historial, de un rango de fechas o de un día: resumen, tasa de ahorro, gastos por categoría y detalle de movimientos (ReportLab).

---

## Tecnologías

| Capa | Herramientas |
|---|---|
| Backend | Python 3 · Flask · Werkzeug · Gunicorn |
| Datos | SQLite |
| Frontend | Plantillas Jinja · Bootstrap 5 · JavaScript · FullCalendar · Chart.js |
| Reportes | ReportLab |
| Pruebas | pytest |
| Despliegue | Render (`render.yaml`, `Procfile`) |

---

## Ejecutar localmente

Requisitos: Python 3.10 o superior.

```bash
git clone https://github.com/santiagomiri/finanpro.git
cd finanpro
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
python app.py
```

La aplicación queda disponible en `http://localhost:5000`. La base de datos se crea automáticamente en el primer arranque.

### Variables de entorno

Ver `.env.example`.

| Variable | Uso | Valor por defecto |
|---|---|---|
| `SECRET_KEY` | Firma de las sesiones | Clave aleatoria temporal (las sesiones se cierran al reiniciar) |
| `DATABASE_PATH` | Ruta del archivo SQLite | `database.db` |
| `PORT` | Puerto del servidor | `5000` |

---

## Pruebas

```bash
pip install pytest
pytest
```

La suite (22 casos) usa una base de datos temporal y cubre, entre otros:

- Conversión de montos en formato colombiano, incluidos valores inválidos o negativos.
- Renovación mensual de gastos fijos y suma de meses en fin de mes (31 de enero → 28 de febrero).
- Presupuesto calculado solo con los gastos del mes actual.
- Edición, movimiento y eliminación de movimientos desde el calendario, y rechazo de tipos inválidos.
- Carga correcta de todas las páginas autenticadas.

---

## Estructura

```
finanpro/
├── app.py              # Rutas, lógica y acceso a datos
├── templates/          # Vistas Jinja (panel, calendario, análisis, reportes…)
├── static/css/         # Estilos
├── tests/test_app.py   # Pruebas con pytest
├── requirements.txt
├── Procfile            # Arranque con Gunicorn
└── render.yaml         # Configuración de despliegue en Render
```

---

## Despliegue

El repositorio incluye la configuración para Render: `render.yaml` instala las dependencias, arranca la app con Gunicorn y genera un `SECRET_KEY` propio.

En el plan gratuito de Render el disco no es persistente, por lo que el archivo SQLite puede reiniciarse. Para uso continuo conviene un disco persistente o una base de datos administrada.

---

Desarrollado por [David Santiago Miranda Ramos](https://github.com/santiagomiri).
