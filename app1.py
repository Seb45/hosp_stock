import streamlit as st
import pandas as pd
import uuid
import qrcode
import datetime
from io import BytesIO
from supabase import create_client, Client
import requests

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Control Hotelería", layout="wide", initial_sidebar_state="expanded")

# --- 1. CONEXIÓN A SUPABASE ---
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- 2. FUNCIONES DE CARGA DE DATOS ---
@st.cache_data(ttl=300) # Reducido a 5 min para mayor frescura
def cargar_catalogos():
    try:
        usu = pd.DataFrame(supabase.table("usuarios").select("*").execute().data)
        ins = pd.DataFrame(supabase.table("insumos").select("*").execute().data)
        sec = pd.DataFrame(supabase.table("sectores").select("*").execute().data)
        return usu, ins, sec
    except Exception as e:
        st.error(f"Error cargando catálogos: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def cargar_movimientos():
    data = supabase.table("movimientos").select("*").order("fecha_hora", desc=True).execute().data
    if not data:
        return pd.DataFrame(columns=["id_mov", "fecha_hora", "tipo", "insumo", "cantidad", "responsable", "sector", "turno", "estado", "usuario_carga"])
    return pd.DataFrame(data)

def generar_qr(url):
    qr = qrcode.make(url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return buffer.getvalue()

def enviar_notificacion_telegram(nombre, rol, email="N/A"):
    token = st.secrets["TELEGRAM_TOKEN"]
    chat_id = st.secrets["TELEGRAM_CHAT_ID"]
    texto = (
        f"🚀 **Nuevo Acceso al Sistema**\n\n"
        f"👤 **Usuario:** {nombre}\n"
        f"🏷️ **Rol:** {rol}\n"
        f"📧 **Email:** {email}\n\n"
        f"✅ _Validado en GestionInsumos_"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
        return True
    except:
        return False

# --- 3. GESTIÓN DE SESIÓN Y AUTENTICACIÓN ---

# Inicializar estados si no existen
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
if 'rol' not in st.session_state:
    st.session_state.rol = None

# A. Lógica de Login/Logout de Supabase Auth
def logout():
    supabase.auth.sign_out()
    st.session_state.usuario = None
    st.session_state.rol = None
    st.query_params.clear()
    st.rerun()

# B. Procesar regreso de Google OAuth
if "code" in st.query_params:
    try:
        # Intercambiar código por sesión
        auth_response = supabase.auth.exchange_code_for_session({"auth_code": st.query_params["code"]})
        # Limpiar URL para evitar bucles
        new_params = {}
        if "confirmar_id" in st.query_params:
            new_params["confirmar_id"] = st.query_params["confirmar_id"]
        st.query_params.clear()
        for k, v in new_params.items():
            st.query_params[k] = v
        st.rerun()
    except Exception as e:
        st.error(f"Error en validación OAuth: {e}")

# C. Sincronizar estado local con Supabase
curr_session = None
try:
    curr_session = supabase.auth.get_session()
except:
    pass

if curr_session and st.session_state.usuario is None:
    user_metadata = curr_session.user.user_metadata
    nombre_google = user_metadata.get("full_name", curr_session.user.email)
    email_google = curr_session.user.email
    
    # Buscar rol en DB
    resp = supabase.table("usuarios").select("rol").eq("nombre", nombre_google).execute()
    rol = resp.data[0]["rol"] if resp.data else "Piso"
    
    st.session_state.update({'usuario': nombre_google, 'rol': rol})
    
    # Notificación Telegram (solo una vez)
    user_check = supabase.table("usuarios").select("notificado").eq("nombre", nombre_google).single().execute()
    if user_check.data and not user_check.data.get("notificado"):
        if enviar_notificacion_telegram(nombre_google, rol, email_google):
            supabase.table("usuarios").update({"notificado": True, "email": email_google}).eq("nombre", nombre_google).execute()

# --- 4. INTERFAZ DE ACCESO (SI NO HAY SESIÓN) ---
df_usu, df_ins, df_sec = cargar_catalogos()

if st.session_state.usuario is None:
    st.title("🔐 Control Stock Insumos")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Acceso Google")
        # Asegurarse que redirect_to sea exacto al configurado en Supabase
        red_url = "https://gestioninsumos.streamlit.app"
        if "confirmar_id" in st.query_params:
            red_url += f"?confirmar_id={st.query_params['confirmar_id']}"
        
        res = supabase.auth.sign_in_with_oauth({
            "provider": "google", 
            "options": {"redirect_to": red_url}
        })
        st.link_button("🌐 Iniciar Sesión con Google", res.url, type="primary")
    
    with col2:
        st.subheader("Acceso PIN")
        with st.form("login_pin"):
            usuarios_pin = df_usu[df_usu["pin"] != "SSO"]["nombre"].tolist()
            u_select = st.selectbox("Usuario", usuarios_pin if usuarios_pin else ["No hay usuarios"])
            p_input = st.text_input("PIN", type="password")
            if st.form_submit_button("Ingresar"):
                match = df_usu[(df_usu["nombre"] == u_select) & (df_usu["pin"].astype(str) == p_input.strip())]
                if not match.empty:
                    st.session_state.update({'usuario': u_select, 'rol': match["rol"].values[0]})
                    st.rerun()
                else:
                    st.error("PIN incorrecto")
    st.stop()

# --- 5. LÓGICA DE VALIDACIÓN POR QR (DESPUÉS DEL LOGIN) ---
df_mov = cargar_movimientos()

if "confirmar_id" in st.query_params:
    cid = "".join(c for c in str(st.query_params["confirmar_id"]) if c.isalnum())
    st.title("📱 Validación de Recepción")
    
    df_mov['id_limpio'] = df_mov['id_mov'].astype(str).apply(lambda x: "".join(c for c in x if c.isalnum()))
    mov_pend = df_mov[df_mov['id_limpio'] == cid]
    
    if not mov_pend.empty:
        if mov_pend.iloc[0]["estado"] == "Confirmado":
            st.success("✅ Esta transacción ya fue confirmada.")
        else:
            st.info(f"**Pedido de:** {mov_pend.iloc[0]['responsable']}")
            st.dataframe(mov_pend[["insumo", "cantidad"]], hide_index=True)
            
            # Verificar si el usuario logueado es el responsable
            responsable = mov_pend.iloc[0]['responsable']
            if st.session_state.usuario == responsable:
                if st.button("Confirmar Recepción Ahora", type="primary"):
                    supabase.table("movimientos").update({"estado": "Confirmado"}).eq("id_mov", mov_pend.iloc[0]["id_mov"]).execute()
                    st.success("Confirmado correctamente.")
                    st.balloons()
            else:
                st.warning(f"Atención: Solo **{responsable}** puede confirmar esto.")
    else:
        st.error("Pedido no encontrado.")
    
    if st.button("Ir al Panel Principal"):
        st.query_params.clear()
        st.rerun()
    st.stop()

# --- 6. PANEL PRINCIPAL ---
st.sidebar.markdown(f"### Bienvenido\n👤 **{st.session_state.usuario}**\n🏷️ Rol: `{st.session_state.rol}`")
if st.sidebar.button("🔴 Cerrar Sesión"):
    logout()

# --- VISTA: ADMIN ---
if st.session_state.rol == "Admin":
    st.header("⚙️ Panel de Administración")
    t1, t2, t3 = st.tabs(["Usuarios", "Insumos", "Sectores"])
    
    with t1:
        st.dataframe(df_usu, use_container_width=True, hide_index=True)
        with st.expander("Añadir Usuario"):
            with st.form("add_u"):
                n = st.text_input("Nombre")
                r = st.selectbox("Rol", ["Piso", "Roperia", "Admin"])
                p = st.text_input("PIN (o poner 'SSO' para Google)")
                if st.form_submit_button("Guardar"):
                    supabase.table("usuarios").insert({"nombre": n, "rol": r, "pin": p}).execute()
                    cargar_catalogos.clear()
                    st.rerun()

# --- VISTA: ROPERIA ---
elif st.session_state.rol == "Roperia":
    st.header("🧺 Gestión de Ropería")
    t_c, t_r = st.tabs(["📥 Cargar Movimiento", "📊 Reporte"])
    
    with t_c:
        tipo = st.radio("Tipo", ["Retiro", "Devolución"], horizontal=True)
        col_a, col_b = st.columns(2)
        sec_sel = col_a.selectbox("Sector", df_sec["nombre"].tolist())
        resp_sel = col_b.selectbox("Responsable (Piso)", df_usu[df_usu["rol"]=="Piso"]["nombre"].tolist())
        
        # Insumos dinámicos
        if 'rows' not in st.session_state: st.session_state.rows = 1
        items = []
        for i in range(st.session_state.rows):
            c1, c2 = st.columns([3, 1])
            ins_item = c1.selectbox(f"Insumo {i+1}", df_ins["nombre"].tolist(), key=f"ins_{i}")
            cant_item = c2.number_input(f"Cant", min_value=1, key=f"can_{i}")
            items.append({"insumo": ins_item, "cantidad": cant_item})
        
        if st.button("➕ Insumo"): 
            st.session_state.rows += 1
            st.rerun()
            
        if st.button("💾 Registrar y Generar QR", type="primary"):
            m_id = str(uuid.uuid4())[:8]
            filas = [{"id_mov": m_id, "tipo": tipo, "insumo": x["insumo"], "cantidad": x["cantidad"], "responsable": resp_sel, "sector": sec_sel, "usuario_carga": st.session_state.usuario} for x in items]
            supabase.table("movimientos").insert(filas).execute()
            st.image(generar_qr(f"https://gestioninsumos.streamlit.app?confirmar_id={m_id}"), caption=f"ID: {m_id}")

# --- VISTA: PISO ---
elif st.session_state.rol == "Piso":
    st.header(f"🏥 Panel de {st.session_state.usuario}")
    # Pendientes
    pends = supabase.table("movimientos").select("*").eq("responsable", st.session_state.usuario).eq("estado", "Pendiente").execute().data
    if pends:
        df_p = pd.DataFrame(pends)
        for id_m in df_p["id_mov"].unique():
            with st.container(border=True):
                data_m = df_p[df_p["id_mov"] == id_m]
                st.write(f"**Pedido {id_m}** - {data_m.iloc[0]['sector']}")
                st.write(", ".join([f"{r['insumo']} (x{r['cantidad']})" for _, r in data_m.iterrows()]))
                if st.button("Confirmar", key=f"btn_{id_m}"):
                    supabase.table("movimientos").update({"estado": "Confirmado"}).eq("id_mov", id_m).execute()
                    st.rerun()
    else:
        st.info("No tienes pedidos pendientes.")
