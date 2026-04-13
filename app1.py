import streamlit as st
import pandas as pd
import os
import uuid
import qrcode
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Control Hotelería", layout="wide", initial_sidebar_state="expanded")

# --- 1. CONFIGURACIÓN DE ARCHIVOS ---
FILE_MOV = "movimientos.csv"
FILE_USU = "usuarios.csv"
FILE_INS = "insumos.csv"
FILE_SEC = "sectores.csv"

def inicializar_archivos():
    if not os.path.exists(FILE_USU):
        pd.DataFrame({
            "Nombre": ["Admin Roperia", "Juan Piso 1", "Maria UTI"],
            "Rol": ["Roperia", "Piso", "Piso"],
            "PIN": ["1234", "1111", "2222"]
        }).to_csv(FILE_USU, index=False)
        
    if not os.path.exists(FILE_MOV):
        pd.DataFrame(columns=[
            "ID_Mov", "Fecha_Hora", "Tipo", "Insumo", "Cantidad", 
            "Responsable", "Sector", "Turno", "Estado", "Usuario_Carga"
        ]).to_csv(FILE_MOV, index=False)
        
    if not os.path.exists(FILE_INS):
        pd.DataFrame({"Nombre": ["Kit Cama Estándar (1 Sábana, 1 Funda)", "Sábana 1 Plaza", "Frazada", "Toalla Baño"]}).to_csv(FILE_INS, index=False)
    if not os.path.exists(FILE_SEC):
        pd.DataFrame({"Nombre": ["Guardia (Planta Baja)", "Piso 1", "UTI"]}).to_csv(FILE_SEC, index=False)

inicializar_archivos()

# --- 2. FUNCIONES ---
def cargar_datos():
    return pd.read_csv(FILE_MOV), pd.read_csv(FILE_USU), pd.read_csv(FILE_INS), pd.read_csv(FILE_SEC)

def generar_qr(url):
    qr = qrcode.make(url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return buffer.getvalue()

df_mov, df_usu, df_ins, df_sec = cargar_datos()

# --- 3. LÓGICA DE CÓDIGO QR (VALIDACIÓN) ---
params = st.query_params
if "confirmar_id" in params:
    id_a_confirmar = params["confirmar_id"]
    st.title("📱 Validación de Recepción")
    
    movimientos = df_mov[df_mov['ID_Mov'] == id_a_confirmar]
    
    if not movimientos.empty:
        # Verificamos el estado del primer registro (todos comparten el mismo estado por ID)
        if movimientos.iloc[0]["Estado"] == "Confirmado":
            st.success("✅ Esta transacción ya fue confirmada previamente.")
        else:
            tipo_op = movimientos.iloc[0]['Tipo']
            responsable = movimientos.iloc[0]['Responsable']
            
            st.info(f"**Operación:** {tipo_op} | **Sector:** {movimientos.iloc[0]['Sector']}")
            
            # Mostrar tabla resumen de lo que se está llevando/devolviendo
            st.write(f"**Detalle a confirmar por {responsable}:**")
            st.dataframe(movimientos[['Cantidad', 'Insumo']], hide_index=True, use_container_width=True)
            
            pin_ingresado = st.text_input("Ingrese su PIN para firmar:", type="password")
            if st.button("Firmar y Confirmar", type="primary"):
                pin_real = str(df_usu[df_usu["Nombre"] == responsable]["PIN"].values[0])
                if pin_ingresado == pin_real:
                    # Actualizar TODAS las filas que tengan ese ID
                    df_mov.loc[df_mov['ID_Mov'] == id_a_confirmar, "Estado"] = "Confirmado"
                    df_mov.to_csv(FILE_MOV, index=False)
                    st.success("✅ ¡Firma digital exitosa! Ya puedes cerrar esta ventana.")
                    st.balloons()
                else:
                    st.error("PIN incorrecto. Intente nuevamente.")
    else:
        st.error("Código QR no válido o expirado.")
        
    st.stop()

# --- 4. SISTEMA DE LOGIN ---
if 'usuario' not in st.session_state:
    st.session_state.update({'usuario': None, 'rol': None})

if st.session_state.usuario is None:
    st.title("🔐 Acceso")
    with st.form("login"):
        user = st.selectbox("Usuario", df_usu["Nombre"].tolist())
        pin = st.text_input("PIN", type="password")
        if st.form_submit_button("Ingresar"):
            data = df_usu[(df_usu["Nombre"] == user) & (df_usu["PIN"].astype(str) == pin)]
            if not data.empty:
                st.session_state.update({'usuario': user, 'rol': data["Rol"].values[0]})
                st.rerun()
            else:
                st.error("Credenciales incorrectas")
    st.stop()

# --- 5. APLICACIÓN PRINCIPAL ---
st.sidebar.write(f"👤 **{st.session_state.usuario}** ({st.session_state.rol})")
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.clear()
    st.rerun()

if st.session_state.rol == "Roperia":
    menu = st.sidebar.selectbox("Menú", ["Nuevo Registro", "Auditoría"])
    
    if menu == "Nuevo Registro":
        # --- ESTILOS CSS INYECTADOS PARA EL LOOK DE LA IMAGEN ---
        st.markdown("""
        <style>
        /* Estilo para el botón principal verde */
        button[kind="primary"] {
            background-color: #28a745 !important;
            color: white !important;
            border-radius: 8px !important;
            font-weight: bold !important;
            padding: 15px !important;
        }
        </style>
        """, unsafe_allow_html=True)

        st.markdown("### 📋 Nuevo Registro")
        
        # URL de tu app en la nube
        url_app_nube = "https://stockinsumos.streamlit.app"
        
        # Variables de estado para los múltiples inputs
        if 'num_insumos' not in st.session_state:
            st.session_state.num_insumos = 1
        if 'qr_generado' not in st.session_state:
            st.session_state.qr_generado = None

        # 1. Toggle de Retiro/Devolución
        tipo_operacion = st.radio("Operación", ["⬆️ Retiro", "⬇️ Devolución"], horizontal=True, label_visibility="collapsed")
        st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)

        # 2. Sector y Turno
        col1, col2 = st.columns(2)
        sector = col1.selectbox("Sector / Piso", df_sec["Nombre"].tolist())
        turno = col2.selectbox("Turno", ["Mañana", "Tarde", "Noche"])
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.write("**Insumos (Kit o Individual)**")
        
        # 3. Filas dinámicas de insumos
        insumos_seleccionados = []
        for i in range(st.session_state.num_insumos):
            c1, c2 = st.columns([3, 1])
            ins = c1.selectbox("Insumo", df_ins["Nombre"].tolist(), key=f"ins_{i}", label_visibility="collapsed")
            cant = c2.number_input("Cant", min_value=1, step=1, key=f"cant_{i}", label_visibility="collapsed")
            insumos_seleccionados.append({"Insumo": ins, "Cantidad": cant})
            
        # Botón para agregar fila
        if st.button("➕ Añadir otro insumo"):
            st.session_state.num_insumos += 1
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        
        # 4. Responsable
        responsable = st.selectbox("Usuario Responsable (Quien retira)", df_usu[df_usu["Rol"] == "Piso"]["Nombre"].tolist())
        st.markdown("<br>", unsafe_allow_html=True)

        # 5. Generación del caso
        if st.button("🟩 Generar QR de Confirmación", type="primary", use_container_width=True):
            nuevo_id = str(uuid.uuid4())[:8] 
            fecha_act = datetime.now().strftime("%Y-%m-%d %H:%M")
            tipo_final = "Retiro" if "Retiro" in tipo_operacion else "Devolución"
            
            nuevos_registros = []
            for item in insumos_seleccionados:
                nuevos_registros.append({
                    "ID_Mov": nuevo_id, "Fecha_Hora": fecha_act,
                    "Tipo": tipo_final, "Insumo": item["Insumo"], "Cantidad": item["Cantidad"],
                    "Responsable": responsable, "Sector": sector, "Turno": turno,
                    "Estado": "Pendiente", "Usuario_Carga": st.session_state.usuario
                })
                
            # Guardado en bloque
            df_nuevos = pd.DataFrame(nuevos_registros)
            df_nuevos.to_csv(FILE_MOV, mode='a', header=df_mov.empty, index=False)
            
            st.session_state.qr_generado = nuevo_id
            st.success(f"Transacción {nuevo_id} generada con {len(insumos_seleccionados)} ítems.")
            
        # 6. Pantalla del QR (Aparece abajo tras presionar el botón)
        if st.session_state.qr_generado:
            st.markdown("---")
            url_qr = f"{url_app_nube}/?confirmar_id={st.session_state.qr_generado}"
            col_qr1, col_qr2 = st.columns([1, 2])
            with col_qr1:
                img_qr = generar_qr(url_qr)
                st.image(img_qr, caption="Pide al receptor que escanee para firmar")
            with col_qr2:
                st.info("El caso queda en estado 'Pendiente' hasta que se lea este código.")
                if st.button("Limpiar formulario y cargar otro"):
                    st.session_state.num_insumos = 1
                    st.session_state.qr_generado = None
                    st.rerun()

    elif menu == "Auditoría":
        st.header("📊 Movimientos y Estados")
        st.dataframe(df_mov, use_container_width=True)

elif st.session_state.rol == "Piso":
    st.header("🛎️ Mis Tareas Pendientes")
    pendientes = df_mov[(df_mov["Responsable"] == st.session_state.usuario) & (df_mov["Estado"] == "Pendiente")]
    if pendientes.empty:
        st.success("Todo al día.")
    else:
        st.dataframe(pendientes[["ID_Mov", "Fecha_Hora", "Tipo", "Cantidad", "Insumo"]])