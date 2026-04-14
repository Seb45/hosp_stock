import streamlit as st
import pandas as pd
import uuid
import qrcode
from io import BytesIO
from datetime import datetime
from supabase import create_client, Client

st.set_page_config(page_title="Control Hotelería", layout="wide")

# --- 1. CONEXIÓN A SUPABASE (POSTGRESQL) ---
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- 2. CARGA DE DATOS ---
@st.cache_data(ttl=600) # Memoria caché por 10 minutos para catálogos
def cargar_catalogos():
    usu = pd.DataFrame(supabase.table("usuarios").select("*").execute().data)
    ins = pd.DataFrame(supabase.table("insumos").select("*").execute().data)
    sec = pd.DataFrame(supabase.table("sectores").select("*").execute().data)
    return usu, ins, sec

def cargar_movimientos():
    # Los movimientos se traen en tiempo real sin caché
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

# --- 3. LÓGICA DE VALIDACIÓN POR QR ---
params = st.query_params
if "confirmar_id" in params:
    st.title("📱 Validación de Recepción!")
    
    # 1. Limpieza EXTREMA (Aspiradora de caracteres): 
    # Quitamos espacios invisibles, corchetes o barras que inyecte el celular.
    # Esto deja ÚNICAMENTE letras y números limpios.
    id_bruto = str(params["confirmar_id"])
    id_a_confirmar = "".join(c for c in id_bruto if c.isalnum())
    
    # 2. Limpiamos también la tabla descargada temporalmente para que el cruce sea perfecto
    df_mov['id_limpio'] = df_mov['id_mov'].astype(str).apply(lambda x: "".join(c for c in x if c.isalnum()))
    
    # 3. Cruzamos los datos
    movimientos_pendientes = df_mov[df_mov['id_limpio'] == id_a_confirmar]
    
    if not movimientos_pendientes.empty:
        if movimientos_pendientes.iloc[0]["estado"] == "Confirmado":
            st.success("✅ Esta transacción ya fue confirmada.")
        else:
            st.info(f"**Sector:** {movimientos_pendientes.iloc[0]['sector']}")
            st.write("**Detalle de insumos:**")
            
            # Ocultamos columnas técnicas
            columnas_tecnicas = ["id", "id_mov", "id_limpio", "estado", "usuario_carga", "responsable", "sector", "turno", "fecha_hora"]
            df_mostrar = movimientos_pendientes.drop(columns=columnas_tecnicas, errors="ignore")
            st.dataframe(df_mostrar, hide_index=True)
            
            pin_ingresado = st.text_input("Ingrese su PIN para firmar:", type="password")
            if st.button("Firmar y Confirmar", type="primary"):
                responsable = movimientos_pendientes.iloc[0]['responsable']
                usuario_data = df_usu[df_usu["nombre"] == responsable]
                
                if usuario_data.empty:
                    st.error("Error: El usuario fue eliminado de la base.")
                else:
                    pin_real = str(usuario_data["pin"].values[0]).strip()
                    
                    if pin_ingresado.strip() == pin_real:
                        # Usamos el ID original exacto para que Supabase lo reconozca al guardar
                        id_original = str(movimientos_pendientes.iloc[0]["id_mov"])
                        supabase.table("movimientos").update({"estado": "Confirmado"}).eq("id_mov", id_original).execute()
                        st.success("✅ Firma digital registrada con éxito.")
                        st.balloons()
                    else:
                        st.error("PIN incorrecto.")
    else:
        # Modo diagnóstico: si falla, te mostrará qué está viendo Python realmente
        st.error(f"Transacción '{id_a_confirmar}' no encontrada.")
        st.warning(f"Últimos IDs registrados en la base: {df_mov['id_limpio'].head(3).tolist()}")
    st.stop()

# --- 4. SISTEMA DE LOGIN ---
if 'usuario' not in st.session_state:
    st.session_state.update({'usuario': None, 'rol': None})

if st.session_state.usuario is None:
    st.title("🔐 Acceso")
    with st.form("login"):
        user = st.selectbox("Usuario", df_usu["nombre"].tolist())
        pin = st.text_input("PIN", type="password")
        if st.form_submit_button("Ingresar"):
            data = df_usu[(df_usu["nombre"] == user) & (df_usu["pin"].astype(str) == pin.strip())]
            if not data.empty:
                st.session_state.update({'usuario': user, 'rol': data["rol"].values[0]})
                st.rerun()
            else:
                st.error("Credenciales incorrectas")
    st.stop()

# --- 5. APLICACIÓN PRINCIPAL (ROLES) ---
st.sidebar.write(f"👤 **{st.session_state.usuario}**")
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.clear()
    st.rerun()

if st.session_state.rol == "Roperia":
    menu = st.sidebar.selectbox("Menú", ["Nuevo Registro", "Auditoría"])
    
    if menu == "Nuevo Registro":
        st.markdown("### 📋 Nuevo Registro Multi-Insumo")
        url_app_nube = "https://gestioninsumos.streamlit.app"
        
        if 'num_rows' not in st.session_state: st.session_state.num_rows = 1
        if 'last_qr' not in st.session_state: st.session_state.last_qr = None

        tipo_op = st.radio("Operación", ["Retiro", "Devolución"], horizontal=True)
        col_s, col_t = st.columns(2)
        sector = col_s.selectbox("Sector", df_sec["nombre"].tolist())
        turno = col_t.selectbox("Turno", ["Mañana", "Tarde", "Noche"])
        
        # --- LÓGICA DE INSUMOS DINÁMICOS SIN DUPLICADOS ---
        todos_insumos = df_ins["nombre"].tolist()
        items_data = []
        
        for i in range(st.session_state.num_rows):
            c1, c2 = st.columns([3, 1])
            key_insumo = f"i_{i}"
            key_cant = f"c_{i}"
            
            # 1. Miramos qué insumos ya están seleccionados en las OTRAS filas
            otros_seleccionados = [
                st.session_state[f"i_{j}"] 
                for j in range(st.session_state.num_rows) 
                if j != i and f"i_{j}" in st.session_state
            ]
            
            # 2. Dejamos solo las opciones que nadie más está usando
            opciones_disponibles = [ins for ins in todos_insumos if ins not in otros_seleccionados]
            
            # 3. Dibujamos la fila
            if opciones_disponibles:
                ins = c1.selectbox(f"Insumo {i+1}", opciones_disponibles, key=key_insumo)
                cant = c2.number_input(f"Cant {i+1}", min_value=1, key=key_cant)
                items_data.append({"insumo": ins, "cantidad": cant})
            else:
                st.warning(f"Fila {i+1}: No hay más tipos de insumos para agregar.")
            
        # 4. Solo mostramos el botón "+ Añadir" si todavía quedan insumos libres en el catálogo
        if st.session_state.num_rows < len(todos_insumos):
            if st.button("➕ Añadir Insumo"):
                st.session_state.num_rows += 1
                st.rerun()
        else:
            st.info("💡 Has seleccionado todos los tipos de insumos disponibles en el catálogo.")
        # --------------------------------------------------

        responsable = st.selectbox("Responsable (Piso)", df_usu[df_usu["rol"] == "Piso"]["nombre"].tolist())

        if st.button("🟩 Generar QR y Guardar", type="primary", use_container_width=True):
            nuevo_id = str(uuid.uuid4())[:8]
            
            # Preparar paquete de datos para Postgres
            nuevas_filas = []
            for d in items_data:
                nuevas_filas.append({
                    "id_mov": nuevo_id, 
                    "tipo": tipo_op,
                    "insumo": d["insumo"], 
                    "cantidad": d["cantidad"],
                    "responsable": responsable, 
                    "sector": sector, 
                    "turno": turno,
                    "usuario_carga": st.session_state.usuario
                })
            
            # INSERCIÓN MASIVA EN BASE DE DATOS (A prueba de balas)
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

elif st.session_state.rol == "Piso":
    st.header("🛎️ Mis Tareas Pendientes")
    pendientes = df_mov[(df_mov["responsable"] == st.session_state.usuario) & (df_mov["estado"] == "Pendiente")]
    if pendientes.empty:
        st.success("Todo al día.")
    else:
        st.dataframe(pendientes[["id_mov", "fecha_hora", "tipo", "cantidad", "insumo"]])
