import os
import logging
import requests
import psycopg2
from datetime import datetime
import json
import base64
import io

# Configuración de logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Variables de entorno (Configúralas en tu .env o servidor)
DATABASE_URL = os.getenv('DATABASE_PUBLIC_URL')
N8N_ENDPOINT = os.getenv('N8N_ENDPOINT')

def procesar_documento_pyme(documento_id, image_base64, business_id):
    """
    Procesa fotos de boletas para una empresa específica en Nodospace.
    """
    logger.info(f"🔄 Procesando documento_id={documento_id} para business_id={business_id}")

    try:
        # 1. Enviar a n8n para que Eva lo analice
        logger.info(f"📤 Enviando imagen a Eva en n8n...")
        ocr_data = enviar_a_n8n(image_base64, business_id)

        if not ocr_data:
            raise Exception("Eva (n8n) no pudo procesar la imagen")

        logger.info(f"✅ Datos extraídos por Eva: {ocr_data}")

        # 2. Actualizar la base de datos de Nodospace (Tabla documents)
        actualizar_bd_nodospace(documento_id, ocr_data, business_id, status='procesado')

        return {'success': True, 'documento_id': documento_id, 'data': ocr_data}

    except Exception as e:
        logger.error(f"❌ Error en el proceso: {e}")
        try:
            actualizar_bd_nodospace(documento_id, {'error': str(e)}, business_id, status='error')
        except:
            pass
        raise

def enviar_a_n8n(image_base64, business_id):
    """
    Envía imagen y business_id a n8n.
    """
    try:
        image_bytes = base64.b64decode(image_base64)
        image_file = io.BytesIO(image_bytes)
        image_file.seek(0)

        # Enviamos la imagen y el ID de la empresa como metadatos
        files = {'imagen': ('boleta.jpg', image_file, 'image/jpeg')}
        payload = {'business_id': business_id}

        response = requests.post(N8N_ENDPOINT, files=files, data=payload, timeout=60)
        response.raise_for_status()
        
        return response.json()

    except Exception as e:
        logger.error(f"🌐 Error conectando con Eva en n8n: {e}")
        return None

def actualizar_bd_nodospace(documento_id, ocr_data, business_id, status):
    """
    Actualiza la tabla 'documents' con el esquema de Nodospace.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cursor = conn.cursor()

        # Mapeo de datos del OCR a columnas de Nodospace
        # Nota: Ajusté los nombres para que coincidan con tu imagen de Supabase
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
        logger.info(f"💾 Registro guardado en documentos de la empresa {business_id}")

    except Exception as e:
        logger.error(f"❌ Error al guardar en base de datos: {e}")
        raise