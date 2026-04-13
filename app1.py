import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import uuid
import qrcode
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Control Hotelería", layout="wide")

# --- 1. CONEXIÓN A GOOGLE SHEETS ---
# En la nube, Streamlit buscará la URL en los "Secrets"
conn = st.connection("gsheets", type=GSheetsConnection)


def cargar_datos():
    # ttl = Time To Live (en segundos). 
    # Guardamos las tablas de configuración en memoria por 10 minutos (600 segundos)
    # porque los insumos, sectores y usuarios no cambian constantemente.
    df_usu = conn.read(worksheet="usuarios", ttl=600)
    df_ins = conn.read(worksheet="insumos", ttl=600)
    df_sec = conn.read(worksheet="sectores", ttl=600)
    
    # Los movimientos sí cambian más seguido, pero los cacheamos por 5 segundos
    # para evitar saturar la API si el usuario hace muchos clics rápidos en los botones.
    df_mov = conn.read(worksheet="movimientos", ttl=5)
    
    return df_mov, df_usu, df_ins, df_sec


def generar_qr(url):
    qr = qrcode.make(url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return buffer.getvalue()

# Carga inicial
df_mov, df_usu, df_ins, df_sec = cargar_datos()

# --- 2. LÓGICA DE VALIDACIÓN POR QR ---
params = st.query_params
if "confirmar_id" in params:
    id_a_confirmar = params["confirmar_id"]
    st.title("📱 Validación de Recepción")
    
    # Filtrar el movimiento en el DataFrame de la nube
    movimientos_pendientes = df_mov[df_mov['ID_Mov'].astype(str) == str(id_a_confirmar)]
    
    if not movimientos_pendientes.empty:
        if movimientos_pendientes.iloc[0]["Estado"] == "Confirmado":
            st.success("✅ Esta transacción ya fue confirmada.")
        else:
            st.info(f"**Sector:** {movimientos_pendientes.iloc[0]['Sector']}")
            st.write("**Detalle de insumos:**")
            st.dataframe(movimientos_pendientes[['Cantidad', 'Insumo']], hide_index=True)
            
            pin_ingresado = st.text_input("Ingrese su PIN para firmar:", type="password")
            if st.button("Firmar y Confirmar", type="primary"):
                responsable = movimientos_pendientes.iloc[0]['Responsable']
                usuario_data = df_usu[df_usu["Nombre"] == responsable]
                
                if usuario_data.empty:
                    st.error(f"Error: El usuario '{responsable}' fue eliminado de la base de datos.")
                else:
                    # Forzamos que el PIN real sea texto limpio sin decimales ni espacios
                    pin_real = str(usuario_data["PIN"].values[0]).replace('.0', '').strip()
                    
                    if pin_ingresado.strip() == pin_real:
                        # Actualizar en la nube
                        df_mov.loc[df_mov['ID_Mov'].astype(str) == str(id_a_confirmar), "Estado"] = "Confirmado"
                        conn.update(worksheet="movimientos", data=df_mov)
                        st.success("✅ Firma registrada en la base de datos.")
                        st.balloons()
                    else:
                        st.error("PIN incorrecto.")
    else:
        st.error("Transacción no encontrada.")
    st.stop()

# --- 3. SISTEMA DE LOGIN ---
# --- 3. SISTEMA DE LOGIN ---
if 'usuario' not in st.session_state:
    st.session_state.update({'usuario': None, 'rol': None})

if st.session_state.usuario is None:
    st.title("🔐 Acceso")
    with st.form("login"):
        user = st.selectbox("Usuario", df_usu["Nombre"].tolist())
        pin = st.text_input("PIN", type="password")
        if st.form_submit_button("Ingresar"):
            # Creamos una columna temporal con los PINs totalmente limpios (sin .0 ni espacios)
            df_usu["PIN_Limpio"] = df_usu["PIN"].astype(str).str.replace('.0', '', regex=False).str.strip()
            
            data = df_usu[(df_usu["Nombre"] == user) & (df_usu["PIN_Limpio"] == pin.strip())]
            if not data.empty:
                st.session_state.update({'usuario': user, 'rol': data["Rol"].values[0]})
                st.rerun()
            else:
                st.error("Credenciales incorrectas")
    st.stop()
# --- 4. APLICACIÓN PRINCIPAL (ROLES) ---
st.sidebar.write(f"👤 **{st.session_state.usuario}**")
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.clear()
    st.rerun()

if st.session_state.rol == "Roperia":
    menu = st.sidebar.selectbox("Menú", ["Nuevo Registro", "Auditoría"])
    
    if menu == "Nuevo Registro":
        st.markdown("### 📋 Nuevo Registro Multi-Insumo")
        url_app_nube = "https://stockinsumos.streamlit.app"
        
        if 'num_rows' not in st.session_state: st.session_state.num_rows = 1
        if 'last_qr' not in st.session_state: st.session_state.last_qr = None

        tipo_op = st.radio("Operación", ["Retiro", "Devolución"], horizontal=True)
        col_s, col_t = st.columns(2)
        sector = col_s.selectbox("Sector", df_sec["Nombre"].tolist())
        turno = col_t.selectbox("Turno", ["Mañana", "Tarde", "Noche"])
        
        items_data = []
        for i in range(st.session_state.num_rows):
            c1, c2 = st.columns([3, 1])
            ins = c1.selectbox(f"Insumo {i+1}", df_ins["Nombre"].tolist(), key=f"i_{i}")
            cant = c2.number_input(f"Cant {i+1}", min_value=1, key=f"c_{i}")
            items_data.append({"Insumo": ins, "Cantidad": cant})
            
        if st.button("➕ Añadir Insumo"):
            st.session_state.num_rows += 1
            st.rerun()

        responsable = st.selectbox("Responsable (Piso)", df_usu[df_usu["Rol"] == "Piso"]["Nombre"].tolist())

        if st.button("🟩 Generar QR y Guardar", type="primary", use_container_width=True):
            nuevo_id = str(uuid.uuid4())[:8]
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            # Crear los nuevos registros
            nuevas_filas = []
            for d in items_data:
                nuevas_filas.append({
                    "ID_Mov": nuevo_id, "Fecha_Hora": fecha, "Tipo": tipo_op,
                    "Insumo": d["Insumo"], "Cantidad": d["Cantidad"],
                    "Responsable": responsable, "Sector": sector, "Turno": turno,
                    "Estado": "Pendiente", "Usuario_Carga": st.session_state.usuario
                })
            
            # Actualizar la nube: Concatenamos y subimos
            df_final = pd.concat([df_mov, pd.DataFrame(nuevas_filas)], ignore_index=True)
            conn.update(worksheet="movimientos", data=df_final)
            
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
        st.header("📊 Historial de la Nube")
        st.dataframe(df_mov, use_container_width=True)
