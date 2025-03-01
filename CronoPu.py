from flask import Flask, request, redirect, url_for, render_template_string, flash
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import geopandas as gpd
import folium
from geopy.distance import geodesic
import ipywidgets as widgets
from IPython.display import display
import re

app = Flask(__name__)
app.secret_key = "super_secret_key"  # Necesario para usar flash y sesiones

# Usaremos un diccionario global para simular el session_state de Streamlit.
data_store = {}

# ─────────────────────────────────────────────
# RUTA 1: CARGA DEL ARCHIVO EXCEL
# ─────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        if "file" not in request.files:
            flash("❌ No se encontró el archivo en la solicitud.")
            return redirect(request.url)
        file = request.files["file"]
        if file.filename == "":
            flash("❌ No se seleccionó ningún archivo.")
            return redirect(request.url)
        try:
            df = pd.read_excel(file)

            # Verificar si el archivo tiene datos
            if df.empty:
                flash("❌ El archivo está vacío. Subí un archivo válido.")
                return redirect(request.url)
            else:
                # Columnas requeridas para conversión
                required_columns = ["NETA [M3/D]", "GEO_LATITUDE", "GEO_LONGITUDE", "TIEMPO PLANIFICADO"]
                missing_cols = [col for col in required_columns if col not in df.columns]
                if missing_cols:
                    flash(f"❌ Faltan las siguientes columnas en el archivo: {', '.join(missing_cols)}")
                    return redirect(request.url)

                # Limpieza y conversión optimizada
                for col in required_columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "."), errors="coerce")
                df.dropna(inplace=True)

                # Verificar que existan las columnas necesarias para posteriores pasos
                if "ZONA" not in df.columns or "POZO" not in df.columns:
                    flash("❌ El archivo debe contener las columnas 'ZONA' y 'POZO'.")
                    return redirect(request.url)

                # Guardar el DataFrame en nuestro "session_state"
                data_store["df"] = df

                flash("✅ Archivo cargado con éxito. A continuación se muestran los primeros datos:")
                table = df.head().to_html(classes="table table-striped", index=False)
                return render_template_string(
                    """
                    <h1>CronoPU - Análisis de Pulling 🚛</h1>
                    <p>{{ message }}</p>
                    {{ table|safe }}
                    <br>
                    <a href="{{ url_for('filter_zonas') }}">Continuar a Filtrado de Zonas</a>
                    """,
                    message="Archivo cargado con éxito.",
                    table=table,
                )
        except Exception as e:
            flash(f"❌ Error al procesar el archivo: {e}")
            return redirect(request.url)
    return render_template_string(
        """
        <h1>CronoPU - Análisis de Pulling 🚛</h1>
        <form method="post" enctype="multipart/form-data">
            <label>📂 Subí el archivo Excel con el cronograma:</label><br>
            <input type="file" name="file" accept=".xlsx"><br><br>
            <input type="submit" value="Subir">
        </form>
        """
    )

# ─────────────────────────────────────────────
# RUTA 2: FILTRADO DE ZONAS Y SELECCIÓN DE PULLING
# ─────────────────────────────────────────────
@app.route("/filter", methods=["GET", "POST"])
def filter_zonas():
    if "df" not in data_store:
        flash("Debes subir un archivo Excel primero.")
        return redirect(url_for("upload_file"))
    df = data_store["df"]
    zonas_disponibles = sorted(df["ZONA"].unique().tolist())
    if request.method == "POST":
        zonas_seleccionadas = request.form.getlist("zonas")
        pulling_count = request.form.get("pulling_count")
        if not zonas_seleccionadas:
            flash("Debes seleccionar al menos una zona.")
            return redirect(request.url)
        try:
            pulling_count = int(pulling_count)
        except:
            pulling_count = 3
        # Filtrar el DataFrame por las zonas seleccionadas y ordenar la lista de pozos
        df_filtrado = df[df["ZONA"].isin(zonas_seleccionadas)].copy()
        data_store["df_filtrado"] = df_filtrado
        pozos = sorted(df_filtrado["POZO"].unique().tolist())
        data_store["pozos_disponibles"] = pozos
        data_store["pulling_count"] = pulling_count
        flash(f"Zonas seleccionadas: {', '.join(zonas_seleccionadas)}")
        return redirect(url_for("select_pulling"))
    # Crear HTML para checkbox de zonas
    checkbox_html = ""
    for zona in zonas_disponibles:
        checkbox_html += f'<input type="checkbox" name="zonas" value="{zona}"> {zona}<br>'
    return render_template_string(
        """
        <h1>CronoPU - Análisis de Pulling 🚛</h1>
        <h2>1. Filtrado de Zonas y Selección de Pulling</h2>
        <form method="post">
            <label>Selecciona las zonas:</label><br>
            {{ checkbox_html|safe }}<br>
            <label>Número de Pulling:</label>
            <input type="number" name="pulling_count" min="1" max="10" value="3"><br><br>
            <input type="submit" value="Filtrar Zonas">
        </form>
        """,
        checkbox_html=checkbox_html,
    )

# ─────────────────────────────────────────────
# RUTA 3: SELECCIÓN DE POZOS PARA PULLING
# ─────────────────────────────────────────────
@app.route("/select_pulling", methods=["GET", "POST"])
def select_pulling():
    if "df_filtrado" not in data_store:
        flash("Debes filtrar las zonas primero.")
        return redirect(url_for("filter_zonas"))
    df_filtrado = data_store["df_filtrado"]
    pozos_disponibles = data_store.get("pozos_disponibles", [])
    pulling_count = data_store.get("pulling_count", 3)
    if request.method == "POST":
        pulling_data = {}
        seleccionados = []
        for i in range(1, pulling_count + 1):
            pozo = request.form.get(f"pulling_pozo_{i}")
            tiempo_restante = request.form.get(f"pulling_tiempo_{i}", 0)
            try:
                tiempo_restante = float(tiempo_restante)
            except:
                tiempo_restante = 0.0
            pulling_data[f"Pulling {i}"] = {
                "pozo": pozo,
                "tiempo_restante": tiempo_restante,
            }
            seleccionados.append(pozo)
        if len(seleccionados) != len(set(seleccionados)):
            flash("Error: No puedes seleccionar el mismo pozo para más de un pulling.")
            return redirect(request.url)
        # Agregar latitud y longitud obtenidos del DataFrame filtrado
        for pulling, data in pulling_data.items():
            pozo = data["pozo"]
            registro = df_filtrado[df_filtrado["POZO"] == pozo].iloc[0]
            data["lat"] = registro["GEO_LATITUDE"]
            data["lon"] = registro["GEO_LONGITUDE"]
        data_store["pulling_data"] = pulling_data
        # Actualizar lista de pozos disponibles (quitando los seleccionados)
        todos_pozos = sorted(df_filtrado["POZO"].unique().tolist())
        data_store["pozos_disponibles"] = sorted([p for p in todos_pozos if p not in seleccionados])
        flash("Selección de Pulling confirmada.")
        return redirect(url_for("hs_disponibilidad"))
    # Crear HTML para select de pozos
    select_options = ""
    for pozo in pozos_disponibles:
        select_options += f'<option value="{pozo}">{pozo}</option>'
    form_html = ""
    for i in range(1, pulling_count + 1):
        form_html += f"""
            <h3>Pulling {i}</h3>
            <label>Pozo para Pulling {i}:</label>
            <select name="pulling_pozo_{i}">
                {select_options}
            </select><br>
            <label>Tiempo restante (h) para Pulling {i}:</label>
            <input type="number" step="0.1" name="pulling_tiempo_{i}" value="0.0"><br>
            <hr>
        """
    return render_template_string(
        """
        <h1>CronoPU - Análisis de Pulling 🚛</h1>
        <h2>2. Selección de Pozos para Pulling</h2>
        <form method="post">
            <p>Selecciona el pozo y define el tiempo restante para cada Pulling</p>
            {{ form_html|safe }}
            <input type="submit" value="Confirmar Selección de Pulling">
        </form>
        """,
        form_html=form_html,
    )

# ─────────────────────────────────────────────
# RUTA 4: INGRESO DE HS DISPONIBILIDAD
# ─────────────────────────────────────────────
@app.route("/hs", methods=["GET", "POST"])
def hs_disponibilidad():
    if "pulling_data" not in data_store:
        flash("Debes seleccionar los pozos para pulling primero.")
        return redirect(url_for("select_pulling"))
    pozos_disponibles = data_store.get("pozos_disponibles", [])
    if not pozos_disponibles:
        flash("No hay pozos disponibles para asignar HS.")
        return redirect(url_for("select_pulling"))
    if request.method == "POST":
        hs_disponibilidad = {}
        for pozo in pozos_disponibles:
            hs_val = request.form.get(f"hs_{pozo}", 0)
            try:
                hs_val = float(hs_val)
            except:
                hs_val = 0.0
            hs_disponibilidad[pozo] = hs_val
        data_store["hs_disponibilidad"] = hs_disponibilidad
        flash("HS Disponibilidad confirmada.")
        return redirect(url_for("assign"))
    form_fields = ""
    for pozo in pozos_disponibles:
        form_fields += f"""
            <label>{pozo} (HS):</label>
            <input type="number" step="0.1" name="hs_{pozo}" value="0.0"><br>
        """
    return render_template_string(
        """
        <h1>CronoPU - Análisis de Pulling 🚛</h1>
        <h2>3. Ingreso de HS Disponibilidad de Equipo</h2>
        <form method="post">
            <p>Ingresa la disponibilidad de HS para cada pozo</p>
            {{ form_fields|safe }}
            <input type="submit" value="Confirmar HS Disponibilidad">
        </form>
        """,
        form_fields=form_fields,
    )

# ─────────────────────────────────────────────
# RUTA 5: EJECUCIÓN DEL PROCESO DE ASIGNACIÓN
# ─────────────────────────────────────────────
@app.route("/assign", methods=["GET"])
def assign():
    if "hs_disponibilidad" not in data_store or not data_store.get("hs_disponibilidad"):
        flash("Debes confirmar la disponibilidad de HS antes de continuar.")
        return redirect(url_for("hs_disponibilidad"))

    df = data_store["df"]
    pulling_data = data_store["pulling_data"]
    hs_disponibilidad = data_store["hs_disponibilidad"]

    matriz_prioridad = []
    pozos_ocupados = set()
    pulling_lista = list(pulling_data.items())

    # Función que calcula el coeficiente y la distancia entre dos pozos
    def calcular_coeficiente(pozo_referencia, pozo_candidato):
        hs_disp_equipo = hs_disponibilidad.get(pozo_candidato, 0)
        registro_ref = df[df["POZO"] == pozo_referencia].iloc[0]
        registro_cand = df[df["POZO"] == pozo_candidato].iloc[0]
        distancia = geodesic(
            (registro_ref["GEO_LATITUDE"], registro_ref["GEO_LONGITUDE"]),
            (registro_cand["GEO_LATITUDE"], registro_cand["GEO_LONGITUDE"])
        ).kilometers
        neta = registro_cand["NETA [M3/D]"]
        hs_planificadas = registro_cand["TIEMPO PLANIFICADO"]
        coeficiente = neta / (hs_planificadas + (distancia * 0.5))
        return coeficiente, distancia

    # Función para asignar pozos adicionales a cada pulling
    def asignar_pozos(pulling_asignaciones, nivel):
        no_asignados = [p for p in data_store["pozos_disponibles"] if p not in pozos_ocupados]
        for pulling, data in pulling_lista:
            # Para el primer candidato se usa el pozo actual o el último asignado
            pozo_referencia = pulling_asignaciones[pulling][-1][0] if pulling_asignaciones[pulling] else data["pozo"]
            candidatos = []
            for pozo in no_asignados:
                tiempo_acumulado = sum(
                    df[df["POZO"] == p[0]]["TIEMPO PLANIFICADO"].iloc[0]
                    for p in pulling_asignaciones[pulling]
                )
                if hs_disponibilidad.get(pozo, 0) <= (data["tiempo_restante"] + tiempo_acumulado):
                    coef, dist = calcular_coeficiente(pozo_referencia, pozo)
                    candidatos.append((pozo, coef, dist))
            candidatos.sort(key=lambda x: (-x[1], x[2]))
            if candidatos:
                mejor_candidato = candidatos[0]
                pulling_asignaciones[pulling].append(mejor_candidato)
                pozos_ocupados.add(mejor_candidato[0])
                if mejor_candidato[0] in no_asignados:
                    no_asignados.remove(mejor_candidato[0])
            else:
                flash(f"⚠️ No hay pozos disponibles para asignar como {nivel} en {pulling}.")
        return pulling_asignaciones

    # Inicializar asignaciones para cada pulling
    pulling_asignaciones = {pulling: [] for pulling, _ in pulling_lista}
    pulling_asignaciones = asignar_pozos(pulling_asignaciones, "N+1")
    pulling_asignaciones = asignar_pozos(pulling_asignaciones, "N+2")
    pulling_asignaciones = asignar_pozos(pulling_asignaciones, "N+3")

    # Construcción de la matriz de prioridad
    for pulling, data in pulling_lista:
        pozo_actual = data["pozo"]
        registro_actual = df[df["POZO"] == pozo_actual].iloc[0]
        neta_actual = registro_actual["NETA [M3/D]"]
        tiempo_restante = data["tiempo_restante"]
        seleccionados = pulling_asignaciones.get(pulling, [])[:3]
        while len(seleccionados) < 3:
            seleccionados.append(("N/A", 1, 1))

        # Se obtiene el tiempo planificado para el candidato N+1
        tiempo_planificado_n1_series = df[df["POZO"] == seleccionados[0][0]]["TIEMPO PLANIFICADO"]
        tiempo_planificado_n1 = tiempo_planificado_n1_series.iloc[0] if not tiempo_planificado_n1_series.empty else 1
        
        # Se extrae la NETA del candidato N+1 desde el DataFrame
        registro_n1 = df[df["POZO"] == seleccionados[0][0]].iloc[0]
        neta_n1 = registro_n1["NETA [M3/D]"]
        
        # Se calcula el coeficiente del candidato N+1:
        #   neta del N+1 dividido por (0.5 * distancia entre actual y N+1 + tiempo planificado para N+1)
        coeficiente_n1 = neta_n1 / ((0.5 * seleccionados[0][2]) + tiempo_planificado_n1)
        
        # Se calcula el coeficiente del pozo actual:
        #   neta_actual / tiempo_restante
        coeficiente_actual = neta_actual / tiempo_restante
        
        # Se compara y se decide la recomendación:
        if coeficiente_actual > coeficiente_n1:
            recomendacion = "Abandonar pozo actual y moverse al N+1"
        else:
            recomendacion = "Continuar en pozo actual"
              

        matriz_prioridad.append([
            pulling, pozo_actual, neta_actual, tiempo_restante,
            seleccionados[0][0], seleccionados[0][1], seleccionados[0][2],
            seleccionados[1][0], seleccionados[1][1], seleccionados[1][2],
            seleccionados[2][0], seleccionados[2][1], seleccionados[2][2],
            recomendacion
        ])

    columns = [
        "Pulling", "Pozo Actual", "Neta Actual", "Tiempo Restante (h)",
        "N+1", "Coeficiente N+1", "Distancia N+1 (km)",
        "N+2", "Coeficiente N+2", "Distancia N+2 (km)",
        "N+3", "Coeficiente N+3", "Distancia N+3 (km)", "Recomendación"
    ]
    df_prioridad = pd.DataFrame(matriz_prioridad, columns=columns)
    data_store["df_prioridad"] = df_prioridad
    table = df_prioridad.to_html(classes="table table-striped", index=False)
    flash("Proceso de asignación completado.")
    return render_template_string(
        """
        <h1>CronoPU - Análisis de Pulling 🚛</h1>
        <h2>Resultados de la Asignación de Pozos</h2>
        {{ table|safe }}
        """,
        table=table,
    )

if __name__ == "__main__":
    app.run(debug=True)
