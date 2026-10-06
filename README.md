# 💳 FinanPro

Sistema de gestión financiera personal — listo para deploy en internet gratis.

---

## 🚀 Deploy en Render (GRATIS) — Paso a paso

### 1. Sube el proyecto a GitHub

1. Crea una cuenta en [github.com](https://github.com) si no tienes
2. Crea un nuevo repositorio (botón verde "New") — ponle nombre `finanpro`
3. Marca como **Privado** (recomendado) o Público
4. Abre una terminal en la carpeta del proyecto y ejecuta:

```bash
git init
git add .
git commit -m "FinanPro v1.0"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/finanpro.git
git push -u origin main
```

---

### 2. Deploy en Render

1. Ve a [render.com](https://render.com) y crea cuenta gratis (con tu cuenta de GitHub)
2. Click en **"New +"** → **"Web Service"**
3. Conecta tu repositorio de GitHub (`finanpro`)
4. Configura así:

| Campo | Valor |
|-------|-------|
| Name | finanpro |
| Environment | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app` |

5. En **Environment Variables** agrega:
   - `SECRET_KEY` → escribe cualquier texto largo aleatorio, ej: `finanpro2024xyzabc123`
   - `DATABASE_PATH` → `/opt/render/project/src/database.db`

6. Click **"Create Web Service"**
7. Espera 2-3 minutos y tendrás tu URL pública 🎉

---

## 💻 Correr localmente

```bash
# Instalar dependencias
pip install -r requirements.txt

# Correr
python app.py
```

Abre: http://localhost:5000

---

## 📁 Estructura del proyecto

```
finanpro/
├── app.py                 ← Backend Flask (todas las rutas)
├── requirements.txt       ← Dependencias Python
├── Procfile               ← Configuración para Render/Railway
├── render.yaml            ← Config automática de Render
├── .env.example           ← Variables de entorno de ejemplo
├── .gitignore
├── static/
│   └── css/
│       └── styles.css     ← Estilos completos
└── templates/
    ├── base.html          ← Layout base con sidebar
    ├── login.html
    ├── register.html
    ├── dashboard.html
    ├── gastos_fijos.html
    ├── presupuesto.html
    ├── metas.html
    ├── calendario.html
    ├── analisis.html
    ├── graficas.html
    └── reportes.html
```

---

## ⚠️ Nota sobre la base de datos en Render

Render es "efímero" — el disco se reinicia ocasionalmente en el plan gratis, lo que puede borrar `database.db`.

**Solución recomendada para producción:**
- Usa [Supabase](https://supabase.com) (PostgreSQL gratis) o
- Upgrade a Render Disk ($7/mes)

Para uso personal/demo el plan gratis funciona perfectamente.

---

## 🔧 Tecnologías

- **Backend:** Python 3 + Flask
- **Base de datos:** SQLite
- **Frontend:** Bootstrap 5 + JS Vanilla
- **Calendario:** FullCalendar 6
- **Gráficas:** Chart.js
- **PDF:** ReportLab
- **Deploy:** Render / Railway / cualquier PaaS Python


## 🧪 Pruebas

```bash
pip install pytest
pytest
```
