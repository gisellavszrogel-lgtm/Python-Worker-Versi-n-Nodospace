import os
import logging
import requests
import psycopg2
from datetime import datetime
import json
import base64
import io
from fastapi import FastAPI, Request, BackgroundTasks

# 1. Configuración de FastAPI y Logs
app = FastAPI()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Variables de entorno
DATABASE_URL = os.getenv('DATABASE_PUBLIC_URL')
N8N_ENDPOINT = os.getenv('N8N_ENDPOINT')

# 2. Rutas de la API

@app.get("/")
def home():
    """Ruta de salud para verificar que el worker está online"""
    return {
        "status": "online",
        "message": "Motor de Nodospace operando desde Magallanes",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/procesar")
async def api_procesar_documento(request: Request):
    """
    Endpoint que recibe la petición de n8n o del Front-end
    """
    try:
        datos = await request.json()
        
        # Extraemos los datos necesarios del JSON recibido
        documento_id = datos.get('documento_id')
        image_base64 = datos.get('image_base64')
        business_id = datos.get('business_id')

        if not all([documento_id, image_base64, business_id]):
            return {"error": "Faltan datos obligatorios (documento_id, image_base64 o business_id)"}, 400

        # Ejecutamos la lógica que ya tenías
        resultado = procesar_documento_pyme(documento_id, image_base64, business_id)
        
        return resultado

    except Exception as e:
        logger.error(f"❌ Error en el endpoint /procesar: {e}")
        return {"error": str(e)}, 500

# 3. Tu lógica de procesamiento (Mejorada)

def procesar_documento_pyme(documento_id, image_base64, business_id):
    logger.info(f"🔄 Procesando documento_id={documento_id} para business_id={business_id}")

    try:
        # 1. Enviar a n8n para que Eva lo analice
        logger.info(f"📤 Enviando imagen a Eva en n8n...")
        ocr_data = enviar_a_n8n(image_base64, business_id)

        if not ocr_data:
            raise Exception("Eva (n8n) no devolvió datos válidos")

        logger.info(f"✅ Datos extraídos por Eva: {ocr_data}")

        # 2. Actualizar la base de datos de Nodospace
        actualizar_bd_nodospace(documento_id, ocr_data, business_id, status='procesado')

        return {'success': True, 'documento_id': documento_id, 'data': ocr_data}

    except Exception as e:
        logger.error(f"❌ Error en el proceso: {e}")
        try:
            actualizar_bd_nodospace(documento_id, {'error': str(e)}, business_id, status='error')
        except:
            pass
        return {'success': False, 'error': str(e)}

def enviar_a_n8n(image_base64, business_id):
    if not N8N_ENDPOINT:
        logger.error("❌ N8N_ENDPOINT no configurado")
        return None

    try:
        image_bytes = base64.b64decode(image_base64)
        image_file = io.BytesIO(image_bytes)
        image_file.seek(0)

        files = {'imagen': ('boleta.jpg', image_file, 'image/jpeg')}
        payload = {'business_id': business_id}

        response = requests.post(N8N_ENDPOINT, files=files, data=payload, timeout=60)
        response.raise_for_status()
        
        return response.json()
    except Exception as e:
        logger.error(f"🌐 Error conectando con n8n: {e}")
        return None

def actualizar_bd_nodospace(documento_id, ocr_data, business_id, status):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cursor = conn.cursor()

        monto = ocr_data.get('monto_total')
        fecha_str = ocr_data.get('fecha_emision')
        rut_emisor = ocr_data.get('rut_emisor')
        razon_social = ocr_data.get('razon_social_emisor')

        cursor.execute("""
            UPDATE documents
            SET
                status = %s,
                monto_total = COALESCE(%s, monto_total),
                fecha_emision = COALESCE(%s, fecha_emision),
                rut_emisor = COALESCE(%s, rut_emisor),
                razon_social_emisor = COALESCE(%s, razon_social_emisor),
                metadata = %s,
                updated_at = NOW()
            WHERE id = %s AND business_id = %s
        """, (
            status,
            float(monto) if monto else None,
            fecha_str,
            rut_emisor,
            razon_social,
            json.dumps(ocr_data),
            documento_id,
            business_id
        ))

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"💾 Registro guardado en Supabase")

    except Exception as e:
        logger.error(f"❌ Error BD: {e}")
        raise

# 4. Inicio del servidor (Local)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
