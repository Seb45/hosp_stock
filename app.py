
import streamlit as st
import pandas as pd
import os
import uuid
import qrcode
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Control Hotelería", layout="wide")

# --- 1. CONFIGURACIÓN DE ARCHIVOS ---
FILE_MOV = "movimientos.csv"
FILE_USU = "usuarios.csv"
FILE_INS = "insumos.csv"
FILE_SEC = "sectores.csv"

def inicializar_archivos():
    if not os.path.exists(FILE_USU):
        # Agregamos la columna PIN y Rol
        pd.DataFrame({
            "Nombre": ["Admin Roperia", "Juan Piso 1", "Maria UTI"],
            "Rol": ["Roperia", "Piso", "Piso"],
            "PIN": ["1234", "1111", "2222"]
        }).to_csv(FILE_USU, index=False)
        
    if not os.path.exists(FILE_MOV):
        # Agregamos ID, Estado y Usuario_Carga
        pd.DataFrame(columns=[
            "ID_Mov", "Fecha_Hora", "Tipo", "Insumo", "Cantidad", 
            "Responsable", "Sector", "Turno", "Estado", "Usuario_Carga"
        ]).to_csv(FILE_MOV, index=False)
        
    if not os.path.exists(FILE_INS):
        pd.DataFrame({"Nombre": ["Sábana", "Frazada", "Toalla"]}).to_csv(FILE_INS, index=False)
    if not os.path.exists(FILE_SEC):
        pd.DataFrame({"Nombre": ["Piso 1", "UTI", "Guardia"]}).to_csv(FILE_SEC, index=False)

inicializar_archivos()

# --- 2. FUNCIONES DE DATOS Y QR ---
def cargar_datos():
    return pd.read_csv(FILE_MOV), pd.read_csv(FILE_USU), pd.read_csv(FILE_INS), pd.read_csv(FILE_SEC)

def generar_qr(url):
    qr = qrcode.make(url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return buffer.getvalue()

df_mov, df_usu, df_ins, df_sec = cargar_datos()

# --- 3. LÓGICA DE NAVEGACIÓN POR QR (PANTALLA DE CONFIRMACIÓN) ---
# Si alguien entra por un link escaneado de QR, vemos el parámetro 'confirmar_id'
params = st.query_params
if "confirmar_id" in params:
    id_a_confirmar = params["confirmar_id"]
    st.title("📱 Validación de Recepción")
    
    # Buscar el movimiento
    if id_a_confirmar in df_mov["ID_Mov"].values:
        idx = df_mov.index[df_mov['ID_Mov'] == id_a_confirmar].tolist()[0]
        movimiento = df_mov.iloc[idx]
        
        if movimiento["Estado"] == "Confirmado":
            st.success("Este movimiento ya fue confirmado previamente.")
        else:
            st.info(f"**Detalle del {movimiento['Tipo']}:** {movimiento['Cantidad']}x {movimiento['Insumo']}")
            st.write(f"**Sector:** {movimiento['Sector']} | **Cargado por:** {movimiento['Usuario_Carga']}")
            
            # Pedir PIN de validación
            pin_ingresado = st.text_input("Ingrese su PIN para firmar:", type="password")
            if st.button("Firmar y Confirmar"):
                # Validar PIN del responsable
                pin_real = str(df_usu[df_usu["Nombre"] == movimiento["Responsable"]]["PIN"].values[0])
                if pin_ingresado == pin_real:
                    # Actualizar CSV
                    df_mov.at[idx, "Estado"] = "Confirmado"
                    df_mov.to_csv(FILE_MOV, index=False)
                    st.success("✅ ¡Confirmación exitosa! Ya puedes cerrar esta ventana.")
                    st.balloons()
                else:
                    st.error("PIN incorrecto. Intente nuevamente.")
    else:
        st.error("Código no encontrado en la base de datos.")
        
    st.stop() # Detiene la app aquí para que no muestre el login ni nada más

# --- 4. SISTEMA DE LOGIN (Si no viene de un QR) ---
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
    st.session_state.rol = None

if st.session_state.usuario is None:
    st.title("🔐 Acceso al Sistema")
    with st.form("login_form"):
        usuario = st.selectbox("Usuario", df_usu["Nombre"].tolist())
        pin = st.text_input("PIN", type="password")
        if st.form_submit_button("Ingresar"):
            user_data = df_usu[(df_usu["Nombre"] == usuario) & (df_usu["PIN"].astype(str) == pin)]
            if not user_data.empty:
                st.session_state.usuario = usuario
                st.session_state.rol = user_data["Rol"].values[0]
                st.rerun() # Refresca la página para entrar
            else:
                st.error("Usuario o PIN incorrectos")
    st.stop()

# --- 5. APLICACIÓN PRINCIPAL (Usuarios Logueados) ---
st.sidebar.write(f"👤 **Usuario:** {st.session_state.usuario} ({st.session_state.rol})")
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.usuario = None
    st.session_state.rol = None
    st.rerun()

# Vistas según el ROL
if st.session_state.rol == "Roperia":
    menu = st.sidebar.selectbox("Navegación", ["Registrar Movimiento", "Dashboard y Auditoría"])
    
    if menu == "Registrar Movimiento":
        st.header("📝 Nueva Carga")
        
        # Necesitamos la IP local de tu PC para armar el link del celular
        # ip_local = st.text_input("IP de tu PC (ej: 192.168.1.1) para el QR:", value="localhost")
        # Así quedaría la generación del link para el QR en la nube
        url_app_nube = "https://stockinsumos.streamlit.app/" 
        url_qr = f"{url_app_nube}/?confirmar_id={nuevo_id}"
        
        with st.form("form_carga", clear_on_submit=True):
            tipo = st.selectbox("Operación", ["Retiro", "Devolución"])
            item = st.selectbox("Insumo", df_ins["Nombre"].tolist())
            cant = st.number_input("Cantidad", min_value=1, step=1)
            resp = st.selectbox("Personal que retira/devuelve", df_usu[df_usu["Rol"] == "Piso"]["Nombre"].tolist())
            sector = st.selectbox("Sector", df_sec["Nombre"].tolist())
            turno = st.selectbox("Turno", ["Mañana", "Tarde", "Noche"])
            
            if st.form_submit_button("Generar Caso"):
                # Crear ID único
                nuevo_id = str(uuid.uuid4())[:8] 
                
                nuevo_registro = pd.DataFrame([{
                    "ID_Mov": nuevo_id, "Fecha_Hora": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Tipo": tipo, "Insumo": item, "Cantidad": cant,
                    "Responsable": resp, "Sector": sector, "Turno": turno,
                    "Estado": "Pendiente", "Usuario_Carga": st.session_state.usuario
                }])
                nuevo_registro.to_csv(FILE_MOV, mode='a', header=df_mov.empty, index=False)
                
                st.success("Caso generado. Esperando firma...")
                
                # Generar y mostrar el QR
                url_qr = f"http://{url_app_nube}/?confirmar_id={nuevo_id}"
                img_qr = generar_qr(url_qr)
                st.image(img_qr, caption="Pide al receptor que escanee este QR con su celular", width=300)

    elif menu == "Dashboard y Auditoría":
        st.header("📊 Auditoría de Casos")
        st.dataframe(df_mov, use_container_width=True)

elif st.session_state.rol == "Piso":
    # El usuario de piso (receptor) solo ve lo que tiene pendiente de confirmar
    st.header("🛎️ Mis Tareas Pendientes")
    st.write("Casos esperando tu validación:")
    
    pendientes = df_mov[(df_mov["Responsable"] == st.session_state.usuario) & (df_mov["Estado"] == "Pendiente")]
    
    if pendientes.empty:
        st.success("No tienes insumos pendientes de firmar.")
    else:
        st.dataframe(pendientes[["Fecha_Hora", "Tipo", "Cantidad", "Insumo", "Usuario_Carga"]])