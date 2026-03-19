import os
import io
import traceback
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from PIL import Image
import imagehash
import numpy as np
import cv2
import fitz  # PyMuPDF

# Check if OpenCV QR detector is available
try:
    _qr_detector = cv2.QRCodeDetector()
    QR_AVAILABLE = True
except Exception:
    QR_AVAILABLE = False

from models import init_db, add_scorecard, check_duplicate, get_all_scorecards, delete_scorecard, get_scorecard_count

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'tiff', 'webp', 'pdf'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_qr_data(image):
    """Extract QR code data from a PIL image using OpenCV."""
    if not QR_AVAILABLE:
        return None

    try:
        # Convert PIL Image to OpenCV format (numpy array)
        img_array = np.array(image.convert('RGB'))
        # OpenCV uses BGR, PIL uses RGB
        img_cv = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        # Detect and decode QR codes
        data, points, _ = _qr_detector.detectAndDecode(img_cv)

        if data and len(data) > 0 and data != '':
            return data

        # Try with grayscale for better detection
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        data, points, _ = _qr_detector.detectAndDecode(gray)

        if data and len(data) > 0 and data != '':
            return data

    except Exception as e:
        print(f"QR decode error: {e}")
    return None


def compute_image_hash(image):
    """Compute perceptual hash of the image."""
    try:
        phash = imagehash.phash(image)
        return str(phash)
    except Exception as e:
        print(f"Image hash error: {e}")
        return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_scorecard():
    """Upload a score card and check for duplicates."""
    try:
        # Validate file
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded', 'status': 'error'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected', 'status': 'error'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload an image or PDF', 'status': 'error'}), 400

        # Get student name
        student_name = request.form.get('student_name', '').strip()
        if not student_name:
            return jsonify({'error': 'Student name is required', 'status': 'error'}), 400

        registration_no = request.form.get('registration_no', '').strip()
        gate_score = request.form.get('gate_score', '').strip()

        # Read and process image
        image_bytes = file.read()
        
        if file.filename.lower().endswith('.pdf'):
            try:
                pdf_document = fitz.open(stream=image_bytes, filetype="pdf")
                if len(pdf_document) == 0:
                    return jsonify({'error': 'PDF is empty', 'status': 'error'}), 400
                page = pdf_document.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # upscale for better QR reading
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                pdf_document.close()
            except Exception as e:
                return jsonify({'error': f'Invalid PDF file: {e}', 'status': 'error'}), 400
        else:
            image = Image.open(io.BytesIO(image_bytes))

        # Extract QR code data
        qr_data = extract_qr_data(image)

        # Compute perceptual hash
        image_hash = compute_image_hash(image)

        # Check for duplicates
        duplicate = check_duplicate(qr_data, image_hash)

        if duplicate:
            return jsonify({
                'status': 'duplicate',
                'message': 'DUPLICATE DETECTED! This score card has already been used for a scholarship.',
                'existing_record': {
                    'student_name': duplicate['student_name'],
                    'registration_no': duplicate['registration_no'] or 'N/A',
                    'gate_score': duplicate['gate_score'] or 'N/A',
                    'uploaded_at': duplicate['uploaded_at'],
                    'original_filename': duplicate['original_filename']
                },
                'match_type': 'QR Code' if (qr_data and duplicate.get('qr_data') == qr_data) else 'Image Hash'
            }), 200

        # No duplicate — save the record
        # Save file to disk
        safe_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        filepath = os.path.join(UPLOAD_FOLDER, safe_filename)
        with open(filepath, 'wb') as f:
            f.write(image_bytes)

        record_id = add_scorecard(
            student_name=student_name,
            registration_no=registration_no,
            qr_data=qr_data,
            image_hash=image_hash,
            gate_score=gate_score,
            original_filename=file.filename
        )

        return jsonify({
            'status': 'approved',
            'message': 'Scholarship APPROVED! This score card is verified and unique.',
            'record': {
                'id': record_id,
                'student_name': student_name,
                'registration_no': registration_no,
                'gate_score': gate_score,
                'qr_data_found': qr_data is not None,
                'image_hash': image_hash
            }
        }), 201

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/extract', methods=['POST'])
def extract_text():
    """Extract text from PDF and scan QR code for auto-fill."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded', 'status': 'error'}), 400
            
        file = request.files['file']
        text = ""
        qr_data = None
        image_bytes = file.read()
        
        if file.filename.lower().endswith('.pdf'):
            try:
                pdf_document = fitz.open(stream=image_bytes, filetype="pdf")
                # Only extract text from up to first 3 pages
                for page_num in range(min(3, len(pdf_document))):
                    text += pdf_document.load_page(page_num).get_text() + "\n"
                    
                # Scrape QR Code from the first page if available
                if QR_AVAILABLE and len(pdf_document) > 0:
                    pix = pdf_document.load_page(0).get_pixmap(matrix=fitz.Matrix(2, 2))
                    qr_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    qr_data = extract_qr_data(qr_img)

                pdf_document.close()
            except Exception as e:
                pass # gracefully continue if PDF is somehow mangled
        else:
            try:
                if QR_AVAILABLE:
                    qr_img = Image.open(io.BytesIO(image_bytes))
                    qr_data = extract_qr_data(qr_img)
            except Exception as e:
                pass

        return jsonify({'status': 'success', 'text': text, 'qr_data': qr_data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/scorecards', methods=['GET'])
def list_scorecards():
    """Get all stored scorecards."""
    try:
        scorecards = get_all_scorecards()
        count = get_scorecard_count()
        return jsonify({
            'status': 'success',
            'count': count,
            'scorecards': scorecards
        })
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/scorecards/<int:record_id>', methods=['DELETE'])
def remove_scorecard(record_id):
    """Delete a scorecard entry."""
    try:
        delete_scorecard(record_id)
        return jsonify({'status': 'success', 'message': f'Record {record_id} deleted.'})
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


@app.route('/api/stats', methods=['GET'])
def stats():
    """Get basic stats."""
    try:
        count = get_scorecard_count()
        return jsonify({
            'status': 'success',
            'total_scorecards': count,
            'pyzbar_available': QR_AVAILABLE
        })
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


if __name__ == '__main__':
    init_db()
    print("=" * 60)
    print("  GO Classes - Scholarship Score Card Checker")
    qr_status = "Available" if QR_AVAILABLE else "Not available (will use image hash only)"
    print(f"  QR Code Scanner: {qr_status}")
    print("  Server starting at http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, port=5000)
