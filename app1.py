import streamlit as st
import pandas as pd
import uuid
import qrcode
import datetime
from io import BytesIO
from supabase import create_client, Client

st.set_page_config(page_title="Control Hotelería", layout="wide")

# --- 1. CONEXIÓN A SUPABASE ---
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- 2. CARGA DE DATOS (CATÁLOGOS) ---
@st.cache_data(ttl=600)
def cargar_catalogos():
    usu = pd.DataFrame(supabase.table("usuarios").select("*").execute().data)
    ins = pd.DataFrame(supabase.table("insumos").select("*").execute().data)
    sec = pd.DataFrame(supabase.table("sectores").select("*").execute().data)
    return usu, ins, sec

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

df_usu, df_ins, df_sec = cargar_catalogos()
df_mov = cargar_movimientos()


# --- 3. GESTIÓN DE SESIÓN (HÍBRIDA) ---
if 'usuario' not in st.session_state:
    st.session_state.update({'usuario': None, 'rol': None})

# A. Interceptar regreso de Google OAuth
if "code" in st.query_params:
    try:
        supabase.auth.exchange_code_for_session({"auth_code": st.query_params["code"]})
        if "confirmar_id" in st.query_params:
            cid = st.query_params["confirmar_id"]
            st.query_params.clear()
            st.query_params["confirmar_id"] = cid
        else:
            st.query_params.clear()
        st.rerun()
    except Exception:
        st.error("Error al validar con Google.")

# B. Sincronizar sesión de Google con Streamlit
session = supabase.auth.get_session()
if session and st.session_state.usuario is None:
    user_metadata = session.user.user_metadata
    nombre_google = user_metadata.get("full_name", session.user.email)
    
    # Buscar su rol en la tabla
    resp = supabase.table("usuarios").select("rol").eq("nombre", nombre_google).execute()
    rol = resp.data[0]["rol"] if resp.data else "Piso"
    st.session_state.update({'usuario': nombre_google, 'rol': rol})


# --- 4. LÓGICA DE VALIDACIÓN POR QR ---
if "confirmar_id" in st.query_params:
    id_bruto = str(st.query_params["confirmar_id"])
    id_a_confirmar = "".join(c for c in id_bruto if c.isalnum())
    
    st.title("📱 Validación de Recepción")
    df_mov['id_limpio'] = df_mov['id_mov'].astype(str).apply(lambda x: "".join(c for c in x if c.isalnum()))
    movimientos_pendientes = df_mov[df_mov['id_limpio'] == id_a_confirmar]
    
    if not movimientos_pendientes.empty:
        if movimientos_pendientes.iloc[0]["estado"] == "Confirmado":
            st.success("✅ Esta transacción ya fue confirmada.")
        else:
            st.info(f"**Sector:** {movimientos_pendientes.iloc[0]['sector']}")
            st.write("**Detalle de insumos:**")
            
            columnas_tecnicas = ["id", "id_mov", "id_limpio", "estado", "usuario_carga", "responsable", "sector", "turno", "fecha_hora"]
            df_mostrar = movimientos_pendientes.drop(columns=columnas_tecnicas, errors="ignore")
            st.dataframe(df_mostrar, hide_index=True)
            
            responsable = movimientos_pendientes.iloc[0]['responsable']
            usuario_data = df_usu[df_usu["nombre"] == responsable]
            
            if usuario_data.empty:
                st.error("Error: El usuario responsable fue eliminado de la base.")
            else:
                pin_real = str(usuario_data["pin"].values[0]).strip()
                id_original = str(movimientos_pendientes.iloc[0]["id_mov"])
                
                # BIFURCACIÓN DE FIRMA: SSO vs PIN
                if pin_real == 'SSO':
                    if st.session_state.usuario == responsable:
                        if st.button("Firma Digital y Confirmar", type="primary"):
                            supabase.table("movimientos").update({"estado": "Confirmado"}).eq("id_mov", id_original).execute()
                            st.success("✅ Recepción validada con éxito.")
                            st.balloons()
                    else:
                        st.warning(f"⚠️ Esta transacción pertenece a **{responsable}**.")
                        st.write("Debes iniciar sesión con Google para firmar.")
                        res = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": f"https://gestioninsumos.streamlit.app/?confirmar_id={id_a_confirmar}"}})
                        st.link_button("🌐 Iniciar sesión para Firmar", res.url)
                else:
                    st.write(f"👤 **Firma manual requerida para: {responsable}**")
                    pin_ingresado = st.text_input("Ingrese PIN:", type="password")
                    if st.button("Firmar y Confirmar", type="primary"):
                        if pin_ingresado.strip() == pin_real:
                            supabase.table("movimientos").update({"estado": "Confirmado"}).eq("id_mov", id_original).execute()
                            st.success("✅ Firma registrada con éxito.")
                            st.balloons()
                        else:
                            st.error("PIN incorrecto.")
    else:
        st.error(f"Transacción '{id_a_confirmar}' no encontrada.")
    
    if st.button("Ir al Inicio"):
        st.query_params.clear()
        st.rerun()
    st.stop()


# --- 5. PANTALLA DE ACCESO HÍBRIDO ---
if st.session_state.usuario is None:
    st.title("🔐 Acceso al Sistema Hospitalario")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Opción 1: Cuenta Institucional")
        st.write("Acceso rápido con tu cuenta de Google.")
        res = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": "https://gestioninsumos.streamlit.app"}})
        st.link_button("🌐 Continuar con Google", res.url, type="primary")
    
    with col2:
        st.subheader("Opción 2: Acceso con PIN")
        with st.form("login_pin"):
            # Filtramos para que solo aparezcan los usuarios que NO son de Google
            usuarios_con_pin = df_usu[df_usu["pin"] != "SSO"]["nombre"].tolist()
            user = st.selectbox("Usuario", usuarios_con_pin)
            pin = st.text_input("PIN Numérico", type="password")
            if st.form_submit_button("Ingresar"):
                data = df_usu[(df_usu["nombre"] == user) & (df_usu["pin"].astype(str) == pin.strip())]
                if not data.empty:
                    st.session_state.update({'usuario': user, 'rol': data["rol"].values[0]})
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas")
    st.stop()


# --- 7. APLICACIÓN PRINCIPAL (ROLES) ---
st.sidebar.write(f"👤 **{st.session_state['usuario']}**")
st.sidebar.write(f"🏷️ Rol: **{st.session_state['rol']}**")

if st.sidebar.button("Cerrar Sesión"):
    supabase.auth.sign_out()
    st.session_state["usuario"] = None
    st.session_state["rol"] = None
    st.rerun()
    
    
# ==========================================
# ROL: ADMINISTRADOR
# ==========================================
if st.session_state.rol == "Admin":
    st.header("⚙️ Panel de Control - ABM")
    tab_usu, tab_ins, tab_sec = st.tabs(["👤 Usuarios", "📦 Insumos", "🏥 Sectores"])

    with tab_usu:
        # Agregamos la columna 'email' para que puedas auditar los correos capturados
        columnas_visibles = ["nombre", "rol", "pin"]
        if "email" in df_usu.columns:
            columnas_visibles.append("email")
            
        st.dataframe(df_usu[columnas_visibles], hide_index=True, use_container_width=True)
        
        # Dividimos en 3 columnas para el ABM completo
        col1, col2, col3 = st.columns(3)
        
        with col1:
            with st.form("form_add_usu", clear_on_submit=True):
                st.subheader("➕ Alta Manual")
                n_nom = st.text_input("Nombre y Apellido")
                n_rol = st.selectbox("Rol", ["Piso", "Roperia", "Admin"])
                n_pin = st.text_input("Asignar PIN numérico")
                if st.form_submit_button("Guardar", type="primary"):
                    if n_nom and n_pin:
                        supabase.table("usuarios").insert({"nombre": n_nom, "rol": n_rol, "pin": n_pin}).execute()
                        cargar_catalogos.clear()
                        st.success("Usuario creado.")
                        st.rerun()
                        
        with col2:
            with st.form("form_update_rol"):
                st.subheader("🔄 Modificar Rol")
                u_mod = st.selectbox("Usuario", df_usu["nombre"].tolist())
                n_rol_mod = st.selectbox("Nuevo Rol", ["Piso", "Roperia", "Admin"])
                if st.form_submit_button("Actualizar"):
                    supabase.table("usuarios").update({"rol": n_rol_mod}).eq("nombre", u_mod).execute()
                    cargar_catalogos.clear()
                    st.success("Actualizado.")
                    st.rerun()
                    
        with col3:
            with st.form("form_del_usu"):
                st.subheader("🗑️ Eliminar")
                u_del = st.selectbox("Usuario a eliminar", df_usu["nombre"].tolist())
                if st.form_submit_button("Eliminar Permanente"):
                    # Regla de Seguridad: Evitar auto-eliminación
                    if u_del == st.session_state["usuario"]:
                        st.error("No puedes eliminar tu propia cuenta activa.")
                    else:
                        # 1. (Opcional pero recomendado) Borrar primero de Supabase Auth si es usuario Google
                        # Nota: Esto borra de la tabla pública. Para borrar el acceso real de Google, 
                        # se hace desde la consola de Supabase > Authentication por seguridad extrema.
                        supabase.table("usuarios").delete().eq("nombre", u_del).execute()
                        cargar_catalogos.clear()
                        st.rerun()
    with tab_ins:
        st.dataframe(df_ins[["id", "nombre"]], hide_index=True, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            with st.form("form_add_ins", clear_on_submit=True):
                st.subheader("➕ Agregar Insumo")
                i_nom = st.text_input("Nombre del Insumo")
                if st.form_submit_button("Guardar", type="primary"):
                    if i_nom:
                        supabase.table("insumos").insert({"nombre": i_nom}).execute()
                        cargar_catalogos.clear()
                        st.rerun()
        with col2:
            with st.form("form_del_ins"):
                st.subheader("🗑️ Eliminar Insumo")
                i_del = st.selectbox("Seleccione", df_ins["nombre"].tolist())
                if st.form_submit_button("Eliminar"):
                    supabase.table("insumos").delete().eq("nombre", i_del).execute()
                    cargar_catalogos.clear()
                    st.rerun()

    with tab_sec:
        st.dataframe(df_sec[["id", "nombre"]], hide_index=True, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            with st.form("form_add_sec", clear_on_submit=True):
                st.subheader("➕ Agregar Sector")
                s_nom = st.text_input("Nombre del Sector")
                if st.form_submit_button("Guardar", type="primary"):
                    if s_nom:
                        supabase.table("sectores").insert({"nombre": s_nom}).execute()
                        cargar_catalogos.clear()
                        st.rerun()
        with col2:
            with st.form("form_del_sec"):
                st.subheader("🗑️ Eliminar Sector")
                s_del = st.selectbox("Seleccione", df_sec["nombre"].tolist())
                if st.form_submit_button("Eliminar"):
                    supabase.table("sectores").delete().eq("nombre", s_del).execute()
                    cargar_catalogos.clear()
                    st.rerun()

# ==========================================
# ROL: ROPERIA
# ==========================================
elif st.session_state.rol == "Roperia":
    menu = st.sidebar.selectbox("Menú", ["Nuevo Registro", "Auditoría"])
    
    # NUEVO BOTÓN: Limpia la memoria caché manualmente
    if st.sidebar.button("🔄 Refrescar Catálogos"):
        cargar_catalogos.clear()
        st.rerun()

    if menu == "Nuevo Registro":
        st.markdown("### 📋 Nuevo Registro Multi-Insumo")
        url_app_nube = "https://gestioninsumos.streamlit.app"
        
        if 'num_rows' not in st.session_state: st.session_state.num_rows = 1
        if 'last_qr' not in st.session_state: st.session_state.last_qr = None

        tipo_op = st.radio("Operación", ["Retiro", "Devolución"], horizontal=True)
        col_s, col_t = st.columns(2)
        sector = col_s.selectbox("Sector", df_sec["nombre"].tolist())
        turno = col_t.selectbox("Turno", ["Mañana", "Tarde", "Noche"])
        
        todos_insumos = df_ins["nombre"].tolist()
        items_data = []
        
        for i in range(st.session_state.num_rows):
            c1, c2 = st.columns([3, 1])
            key_insumo = f"i_{i}"
            key_cant = f"c_{i}"
            
            otros_seleccionados = [st.session_state[f"i_{j}"] for j in range(st.session_state.num_rows) if j != i and f"i_{j}" in st.session_state]
            opciones_disponibles = [ins for ins in todos_insumos if ins not in otros_seleccionados]
            
            if opciones_disponibles:
                ins = c1.selectbox(f"Insumo {i+1}", opciones_disponibles, key=key_insumo)
                cant = c2.number_input(f"Cant {i+1}", min_value=1, key=key_cant)
                items_data.append({"insumo": ins, "cantidad": cant})
            else:
                st.warning(f"Fila {i+1}: No hay más tipos de insumos.")
            
        if st.session_state.num_rows < len(todos_insumos):
            if st.button("➕ Añadir Insumo"):
                st.session_state.num_rows += 1
                st.rerun()

        responsable = st.selectbox("Responsable (Piso)", df_usu[df_usu["rol"] == "Piso"]["nombre"].tolist())

        if st.button("🟩 Generar QR y Guardar", type="primary", use_container_width=True):
            nuevo_id = str(uuid.uuid4())[:8]
            nuevas_filas = [{"id_mov": nuevo_id, "tipo": tipo_op, "insumo": d["insumo"], "cantidad": d["cantidad"], "responsable": responsable, "sector": sector, "turno": turno, "usuario_carga": st.session_state.usuario} for d in items_data]
            supabase.table("movimientos").insert(nuevas_filas).execute()
            st.session_state.last_qr = nuevo_id
            st.success(f"Registrado. ID: {nuevo_id}")

        if st.session_state.last_qr:
            url_qr = f"{url_app_nube}/?confirmar_id={st.session_state.last_qr}"
            st.image(generar_qr(url_qr), width=250)
            if st.button("Nueva Carga"):
                st.session_state.num_rows = 1
                st.session_state.last_qr = None
                st.rerun()

    elif menu == "Auditoría":
        st.header("📊 Auditoría en Tiempo Real")
        st.dataframe(df_mov, use_container_width=True)

# ==========================================
# ROL: PISO
# ==========================================
if st.session_state["rol"] == "Piso":
    st.header(f"🏥 Panel de {st.session_state['usuario']}")
    st.subheader("📋 Pendientes de Confirmación")

    try:
        res_p = supabase.table("movimientos").select("*")\
            .eq("responsable", st.session_state["usuario"])\
            .eq("estado", "Pendiente")\
            .order("fecha_hora", desc=True).execute()
        pendientes_data = res_p.data
    except Exception as e:
        st.error(f"Error al consultar pendientes: {e}")
        pendientes_data = []

    if pendientes_data:
        # Agrupar por id_mov
        grupos = {}
        for item in pendientes_data:
            id_mov = item["id_mov"]
            if id_mov not in grupos:
                grupos[id_mov] = {
                    "id_mov": id_mov,
                    "sector": item["sector"],
                    "fecha_hora": item["fecha_hora"],
                    "insumos": []
                }
            grupos[id_mov]["insumos"].append(f"{item['insumo']} x{item['cantidad']}")

        st.write("Confirme o rechace cada pedido recibido:")

        for id_mov, grupo in grupos.items():
            with st.container():
                col_info, col_ok, col_ko = st.columns([3, 0.5, 0.5])

                with col_info:
                    insumos_str = " · ".join(grupo["insumos"])
                    st.markdown(f"**📦 Pedido:** `{id_mov}`")
                    st.markdown(f"{insumos_str}")
                    st.caption(f"Sector: {grupo['sector']} | Fecha: {grupo['fecha_hora'][:16]}")

                with col_ok:
                    if st.button("✅", key=f"piso_ok_{id_mov}", help="Aprobar todo el pedido"):
                        supabase.table("movimientos")\
                            .update({"estado": "Aprobado"})\
                            .eq("id_mov", id_mov)\
                            .execute()
                        st.toast(f"✅ Pedido {id_mov} aprobado")
                        st.rerun()

                with col_ko:
                    if st.button("❌", key=f"piso_ko_{id_mov}", help="Rechazar todo el pedido"):
                        supabase.table("movimientos")\
                            .update({"estado": "Rechazado"})\
                            .eq("id_mov", id_mov)\
                            .execute()
                        st.toast(f"❌ Pedido {id_mov} rechazado")
                        st.rerun()

            st.markdown("---")
    else:
        st.info("No tienes movimientos pendientes en este momento.")
