"""Demo de Memoria Vial Segura: chat GraphRAG, mapa, boletín, dashboard, trazabilidad y SECI.

Ejecutar:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from shapely import wkt
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _secrets_a_entorno() -> None:
    """En Streamlit Cloud las credenciales llegan como secrets; config.py las lee del entorno."""
    import os

    try:
        for k, v in st.secrets.items():
            if isinstance(v, str):
                os.environ.setdefault(k, v)
    except Exception:  # sin secrets.toml (ejecución local con .env)
        pass


_secrets_a_entorno()
import config  # noqa: E402
import llm  # noqa: E402
from agente import consultas  # noqa: E402
from agente.agente import responder  # noqa: E402
from agente.sintesis import RE_CITA_DOC  # noqa: E402
from grafo.conexion import leer  # noqa: E402
from ontologia.catalogos import DIAS, FRANJAS, MEDIOS, MODALIDAD  # noqa: E402

st.set_page_config(page_title="Memoria Vial Segura", page_icon="🛣️", layout="wide")

# Paleta de referencia (dataviz): rampa azul secuencial y slots categóricos 1-2
AZUL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SERIE_1, SERIE_2 = "#2a78d6", "#eb6834"
PREGUNTAS = [
    "¿Dónde se concentran los robos de celular desde moto entre 18:00 y 20:00 cerca de paraderos en la última semana?",
    "¿Bajaron los arrebatos en los tramos con patrullaje reforzado en septiembre?",
    "¿Qué modalidades nuevas aparecieron esta semana en vías sin registros el último mes?",
]


def aviso() -> None:
    st.warning(f"**{config.ETIQUETA_SINTETICO}** · Red vial y POIs reales de OpenStreetMap; incidentes simulados y "
               "calibrados con cifras agregadas INEI/SIDPOL. Sin datos de personas (Ley 29733).", icon="⚠️")


# --- Datos cacheados ------------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def tramos_todos() -> pd.DataFrame:
    feats = json.loads((config.GEO / "tramos.geojson").read_text(encoding="utf-8"))["features"]
    return pd.DataFrame([f["properties"] for f in feats])


@st.cache_data(ttl=600, show_spinner=False)
def pois(tipo: str) -> list[dict]:
    feats = json.loads((config.GEO / "pois.geojson").read_text(encoding="utf-8"))["features"]
    return [dict(p["properties"], lon=p["geometry"]["coordinates"][0], lat=p["geometry"]["coordinates"][1])
            for p in feats if p["properties"]["tipo"] == tipo]


@st.cache_data(ttl=60, show_spinner=False)
def datos_mapa(desde: str, hasta: str, modalidad, medio, franja) -> pd.DataFrame:
    return pd.DataFrame(consultas.incidentes_mapa(desde, hasta, modalidad, medio, franja))


@st.cache_data(ttl=60, show_spinner=False)
def serie() -> pd.DataFrame:
    return pd.DataFrame(consultas.serie_diaria())


@st.cache_data(ttl=60, show_spinner=False)
def heat() -> pd.DataFrame:
    return pd.DataFrame(consultas.franja_por_dia())


@st.cache_data(ttl=60, show_spinner=False)
def calidad() -> pd.DataFrame:
    return pd.DataFrame(consultas.calidad_pln())


@st.cache_data(ttl=60, show_spinner=False)
def intervenciones() -> pd.DataFrame:
    filas, _, _ = consultas.efecto_intervencion(tipo="patrullaje reforzado")
    return pd.DataFrame(filas)


def limpiar_cache() -> None:
    st.cache_data.clear()


# --- Trazabilidad -----------------------------------------------------------------------------------
def mostrar_fuente(cita: str) -> None:
    """PROV-O en acción: de la cita al relato original o a la página del PDF con su URL oficial."""
    m = RE_CITA_DOC.fullmatch(f"[{cita}]")
    if re.fullmatch(r"R-\d{6}", cita):
        r = consultas.reporte(cita)
        if not r:
            st.error("La cita no existe en el grafo.")
            return
        st.markdown(f"**Reporte {r['id']}** · tipo `{r['tipo']}` · canal {r['canal']} · ingreso {r['fecha_ingreso']}")
        st.info(r["texto"])
        st.caption(f"Incidente {r['incidente']} — {r['modalidad']} (ICCS {r['iccs']}) · medio: {r['medio']} · "
                   f"{r['fecha']} {r['hora']} ({r['franja']}) · tramo {r['tramo']} ({r['via']} cdra. {r['cuadra']}) · {r['sector']}")
        st.caption("Cadena PROV-O: (:Incidente)-[:DERIVADO_DE]->(:Fuente:Reporte)")
    elif m:
        p = consultas.pagina(m.group(1), int(m.group(2)))
        if not p:
            st.error("La página citada no existe en el grafo.")
            return
        st.markdown(f"**{p['titulo']}** — página {p['pagina']} · [{p['cita']}]  \n[Abrir PDF oficial]({p['url']})")
        st.text_area("Texto extraído de la página", p["texto"], height=260, key=f"pag-{cita}")
    else:
        st.error("Formato de cita no reconocido. Usa R-000123 o INEI-7278873 p.30")


# --- Pestañas -----------------------------------------------------------------------------------------
def pestaña_chat() -> None:
    st.subheader("Agente GraphRAG")
    st.caption(f"Modo: {'Claude (' + config.LLM_MODEL + ') + plantillas Cypher' if llm.disponible() else 'reglas + plantillas Cypher (sin ANTHROPIC_API_KEY)'}")
    cols = st.columns(3)
    for c, q in zip(cols, PREGUNTAS):
        if c.button(q, use_container_width=True):
            st.session_state["pregunta"] = q
    escrita = st.chat_input("Pregunta sobre incidentes, intervenciones o estadísticas de Los Olivos…")
    pregunta = escrita or st.session_state.pop("pregunta", None)
    if pregunta:
        with st.spinner("Consultando el grafo…"):
            st.session_state.setdefault("historial", []).insert(0, responder(pregunta))
    for k, r in enumerate(st.session_state.get("historial", [])[:6]):
        with st.chat_message("user"):
            st.write(r.pregunta)
        with st.chat_message("assistant"):
            st.caption(f"Tipo: **{r.tipo}** · {r.modo} · {r.latencia_s} s")
            st.markdown(r.texto)
            if r.evidencia:
                with st.expander(f"Tabla de evidencia ({len(r.evidencia)} filas)"):
                    df = pd.DataFrame(r.evidencia).drop(columns=["texto", "lat", "lon", "embedding"], errors="ignore")
                    st.dataframe(df, use_container_width=True, hide_index=True)
            if r.cypher:
                with st.expander("Cypher ejecutado (transparencia)"):
                    for c in r.cypher:
                        st.code(c, language="cypher")
                    st.json({k2: v for k2, v in r.parametros.items() if v not in (None, False)})
            if r.citas:
                cita = st.selectbox("Ver la fuente de una cita", ["—"] + r.citas, key=f"cita-{k}")
                if cita != "—":
                    mostrar_fuente(cita)


def pestaña_mapa() -> None:
    st.subheader("Mapa de incidentes por tramo")
    ref = consultas.fecha_referencia()
    c1, c2, c3, c4 = st.columns(4)
    rango = c1.date_input("Rango de fechas", (config.FECHA_INICIO, ref), min_value=config.FECHA_INICIO, max_value=ref)
    mod = c2.selectbox("Modalidad", ["(todas)"] + list(MODALIDAD), format_func=lambda m: MODALIDAD[m]["nombre"] if m in MODALIDAD else m)
    medio = c3.selectbox("Medio", ["(todos)"] + MEDIOS)
    franja = c4.selectbox("Franja", ["(todas)"] + [f[0] for f in FRANJAS])
    desde, hasta = (rango if isinstance(rango, tuple) and len(rango) == 2 else (config.FECHA_INICIO, ref))
    df = datos_mapa(desde.isoformat(), hasta.isoformat(), None if mod.startswith("(") else mod,
                    None if medio.startswith("(") else medio, None if franja.startswith("(") else franja)
    mapa = folium.Map(location=[-11.965, -77.073], zoom_start=14, tiles="OpenStreetMap")  # sin API key
    limite = json.loads((config.GEO / "limite.geojson").read_text(encoding="utf-8"))
    folium.GeoJson(limite, name="Los Olivos", style_function=lambda _: {"color": "#52514e", "weight": 2, "fillOpacity": 0}).add_to(mapa)
    sectores = json.loads((config.GEO / "sectores.json").read_text(encoding="utf-8"))
    for s in sectores:
        folium.Marker([s["lat"], s["lon"]], icon=folium.DivIcon(html=f"<b style='font-size:13px;color:#52514e'>{s['id']}</b>"),
                      tooltip=s["nombre"]).add_to(mapa)
    capa_par = folium.FeatureGroup(name="Paraderos (OSM)")
    for p in pois("paradero"):
        folium.CircleMarker([p["lat"], p["lon"]], radius=3, color="#52514e", fill=True, fill_opacity=0.8,
                            tooltip=f"Paradero: {p['nombre']}").add_to(capa_par)
    capa_par.add_to(mapa)
    if not df.empty:
        maximo = df["n"].max()
        for _, f in df.iterrows():
            geom = wkt.loads(f["wkt"])
            paso = min(len(AZUL) - 1, 2 + int(4 * (f["n"] - 1) / max(1, maximo - 1)))
            folium.PolyLine([(y, x) for x, y in geom.coords], color=AZUL[paso], weight=4 + min(f["n"], 6),
                            tooltip=f"{f['via']} cdra. {f['cuadra']}: {f['n']} incidentes · {' '.join(f['reportes'][:4])}").add_to(mapa)
    folium.LayerControl().add_to(mapa)
    st_folium(mapa, height=600, use_container_width=True, returned_objects=[])
    st.caption(f"{len(df)} tramos con incidentes · color y grosor ∝ número de incidentes (azul claro → oscuro). "
               "Sectores de patrullaje ficticios (k-means).")
    if not df.empty:
        st.dataframe(df.drop(columns=["wkt"]).sort_values("n", ascending=False).head(20), hide_index=True, use_container_width=True)


def pestaña_boletin() -> None:
    from flujo.run_daily import dias_disponibles, revertir_despues_de, simular, ultimo_procesado

    st.subheader("Boletín para el turno siguiente")
    ultimo = ultimo_procesado()
    pendientes = [d for d in dias_disponibles() if ultimo is None or d > ultimo]
    c1, c2, c3 = st.columns([2, 2, 3])
    c1.metric("Último día procesado", str(ultimo or "—"))
    c2.metric("Días pendientes de ingresar", len(pendientes))
    if c3.button("▶️ Ejecutar ciclo diario (siguiente día)", disabled=not pendientes, use_container_width=True):
        antes = leer("MATCH (i:Incidente) RETURN count(i) AS n")[0]["n"]
        with st.spinner("Reportes → PLN → grafo → boletín…"):
            res = simular(1)
        limpiar_cache()
        if res:
            r = res[0]
            st.success(f"Día {r['fecha']}: {r['n_reportes']} reportes nuevos · {r['n_ok']} completos · "
                       f"{r['n_sin_tramo']} sin tramo. Incidentes en el grafo: {antes} → {antes + r['n_reportes']}")
        st.rerun()
    with st.expander("Preparar la demo en clase"):
        fecha = st.date_input("Revertir el grafo a esta fecha (luego ejecuta el ciclo día por día)", date(2026, 10, 13))
        if st.button("Revertir"):
            n = revertir_despues_de(fecha)
            limpiar_cache()
            st.info(f"Se borraron {n} incidentes posteriores al {fecha}.")
            st.rerun()
    boletines = sorted(config.BOLETINES.glob("boletin_*.md"))
    if not boletines:
        st.info("Aún no hay boletines. Ejecuta el flujo diario.")
        return
    elegido = st.selectbox("Boletín", boletines[::-1], format_func=lambda p: p.stem.replace("boletin_", ""))
    st.markdown(elegido.read_text(encoding="utf-8"))
    st.download_button("Descargar HTML", elegido.with_suffix(".html").read_bytes(), file_name=elegido.with_suffix(".html").name)


def pestaña_dashboard() -> None:
    st.subheader("Dashboard")
    s, c = serie(), calidad()
    if s.empty:
        st.info("Sin incidentes cargados.")
        return
    total = int(s["n"].sum())
    resueltos = int((c["n_reportes"] - c["n_sin_tramo"]).sum()) if not c.empty else 0
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Incidentes", total)
    k2.metric("Días procesados", len(c))
    k3.metric("Tramo resuelto (PLN)", f"{100 * resueltos / max(1, c['n_reportes'].sum()):.1f} %")
    k4.metric("Modalidades distintas", s["modalidad"].nunique())

    col1, col2 = st.columns(2)
    por_dia = s.groupby("fecha", as_index=False)["n"].sum()
    fig = px.line(por_dia, x="fecha", y="n", labels={"fecha": "Fecha", "n": "Incidentes"}, title="Incidentes por día")
    fig.update_traces(line=dict(color=SERIE_1, width=2), hovertemplate="%{x}: %{y} incidentes<extra></extra>")
    fig.update_layout(hovermode="x unified", margin=dict(t=50, b=10))
    col1.plotly_chart(fig, use_container_width=True)

    por_mod = s.groupby("modalidad", as_index=False)["n"].sum().sort_values("n")
    fig = px.bar(por_mod, x="n", y="modalidad", orientation="h", title="Incidentes por modalidad",
                 labels={"n": "Incidentes", "modalidad": ""}, text="n")
    fig.update_traces(marker_color=SERIE_1, textposition="outside", hovertemplate="%{y}: %{x}<extra></extra>")
    fig.update_layout(margin=dict(t=50, b=10), bargap=0.25)
    col2.plotly_chart(fig, use_container_width=True)

    h = heat()
    tabla = h.pivot_table(index="franja", columns="dia", values="n", aggfunc="sum", fill_value=0)
    tabla = tabla.reindex(index=[f[0] for f in FRANJAS], columns=DIAS, fill_value=0)
    fig = go.Figure(go.Heatmap(z=tabla.values, x=[d.capitalize() for d in DIAS], y=[f.capitalize() for f in tabla.index],
                               colorscale=[[i / (len(AZUL) - 1), c_] for i, c_ in enumerate(AZUL)], xgap=2, ygap=2,
                               text=tabla.values, texttemplate="%{text}",
                               hovertemplate="%{y}, %{x}: %{z} incidentes<extra></extra>", colorbar=dict(title="Incidentes")))
    fig.update_layout(title="Franja horaria × día de la semana", margin=dict(t=50, b=10))
    col1.plotly_chart(fig, use_container_width=True)

    iv = intervenciones()
    if not iv.empty:
        iv["tramo_txt"] = iv["via"].str.replace("Avenida ", "Av. ") + " cdra. " + iv["cuadra"].astype(str)
        fig = go.Figure([go.Bar(name="4 semanas antes", x=iv["tramo_txt"], y=iv["antes"], marker_color=SERIE_1),
                         go.Bar(name="4 semanas después", x=iv["tramo_txt"], y=iv["despues"], marker_color=SERIE_2)])
        fig.update_layout(barmode="group", title="Arrebatos antes / después del patrullaje reforzado (descriptivo)",
                          yaxis_title="Arrebatos", legend=dict(orientation="h", y=1.12), margin=dict(t=70, b=10), bargap=0.3)
        fig.update_traces(hovertemplate="%{x}: %{y}<extra>%{fullData.name}</extra>")
        col2.plotly_chart(fig, use_container_width=True)

    if not c.empty:
        c = c[c["n_reportes"] > 0].copy()
        c["pct"] = 100 * (c["n_reportes"] - c["n_sin_tramo"]) / c["n_reportes"]
        fig = px.line(c, x="fecha", y="pct", title="Calidad del PLN: % de reportes con tramo resuelto por corrida",
                      labels={"fecha": "Corrida", "pct": "% con tramo"})
        fig.update_traces(line=dict(color=SERIE_1, width=2), hovertemplate="%{x}: %{y:.0f} %<extra></extra>")
        fig.update_yaxes(range=[0, 105])
        st.plotly_chart(fig, use_container_width=True)
    eval_md = config.REPORTS / "eval_pln.md"
    if eval_md.exists():
        with st.expander("Evaluación del PLN contra ground truth"):
            st.markdown(eval_md.read_text(encoding="utf-8"))


def pestaña_trazabilidad() -> None:
    st.subheader("Trazabilidad (PROV-O)")
    st.write("Toda respuesta remonta a su fuente: un reporte `[R-000123]` o una página oficial `[INEI-7278873 p.30]`.")
    cita = st.text_input("Cita", "R-000350")
    if cita:
        mostrar_fuente(cita.strip("[] "))


def pestaña_seci() -> None:
    st.subheader("Modelo SECI (Nonaka y Takeuchi) en la demo")
    st.markdown("""
| Fase | Qué ocurre | Dónde se ve en la demo |
|---|---|---|
| **Socialización** (tácito → tácito) | Serenos y efectivos comparten lo que observan en la calle en el relevo de turno. | El **boletín** se lee en el relevo; los relatos libres conservan la voz del sereno. |
| **Externalización** (tácito → explícito) | El relato libre se convierte en datos: vía, cuadra, hora, modalidad, medio. | **PLN** (`pln/extraer.py`) y la tabla de evidencia del chat. |
| **Combinación** (explícito → explícito) | Se integran reportes, OSM, intervenciones y estadísticas INEI/SIDPOL en un grafo con ontología. | **Grafo Neo4j**, **mapa** y **dashboard**; respuestas multi-salto del agente. |
| **Internalización** (explícito → tácito) | El personal aprende patrones y ajusta su patrullaje. | **Recomendaciones del boletín**, preguntas al agente y comparación antes/después. |
""")
    st.caption("Cada respuesta cita su fuente (PROV-O), de modo que el conocimiento combinado sigue siendo verificable.")


def main() -> None:
    st.title("🛣️ Memoria Vial Segura — Los Olivos")
    aviso()
    tabs = st.tabs(["💬 Chat", "🗺️ Mapa", "📰 Boletín", "📊 Dashboard", "🔗 Trazabilidad", "🔄 SECI"])
    with tabs[0]:
        pestaña_chat()
    with tabs[1]:
        pestaña_mapa()
    with tabs[2]:
        pestaña_boletin()
    with tabs[3]:
        pestaña_dashboard()
    with tabs[4]:
        pestaña_trazabilidad()
    with tabs[5]:
        pestaña_seci()


main()
