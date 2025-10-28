import streamlit as st
import os
import base64
from datetime import datetime
from pdf2image import convert_from_path
from PyPDF2 import PdfReader, PdfWriter
from openai import OpenAI
from difflib import SequenceMatcher
import json
import csv
import tempfile

# OpenAI client
client = OpenAI()

st.set_page_config(
    page_title="Amazon送り状並べ替えツール",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Amazon送り状並べ替えツール")
st.markdown("---")

st.markdown("""
### 使い方
1. **納品書PDF**をアップロード（全店舗分が含まれていてもOK）
2. **送り状PDF**をアップロード
3. **並べ替え実行**ボタンをクリック
4. 処理完了後、並べ替え済み送り状PDFと不一致リストCSVをダウンロード

**処理内容:**
- 納品書からAmazon店の注文のみを抽出
- 送り状と照合（郵便番号と名前でマッチング）
- 納品書の順番に従って送り状を並べ替え
- 納品書にあるが送り状にない注文をリストアップ
""")

st.markdown("---")

# File uploaders
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 納品書PDF")
    delivery_note_file = st.file_uploader(
        "納品書PDFをアップロード",
        type=['pdf'],
        key="delivery_note"
    )

with col2:
    st.subheader("📋 送り状PDF")
    shipping_label_file = st.file_uploader(
        "送り状PDFをアップロード",
        type=['pdf'],
        key="shipping_label"
    )

st.markdown("---")


def encode_image(image_path):
    """画像をbase64エンコード"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def extract_delivery_note_info(pdf_path, max_pages=None):
    """納品書からAmazon注文情報を抽出"""
    st.info(f"📖 納品書を読み込んでいます...")
    
    images = convert_from_path(pdf_path, dpi=150)
    
    if max_pages:
        images = images[:max_pages]
    
    orders = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, image in enumerate(images):
        status_text.text(f"納品書 {i+1}/{len(images)} ページを処理中...")
        progress_bar.progress((i + 1) / len(images))
        
        temp_image_path = f"/tmp/delivery_note_page_{i+1}.jpg"
        image.save(temp_image_path, 'JPEG')
        
        base64_image = encode_image(temp_image_path)
        
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """この納品書画像から以下の情報を抽出してください:
1. 店舗名（「メイアイストア amazon店」かどうか）
2. 管理番号（No.）
3. 注文番号
4. お届け先の郵便番号（〒を除く）
5. お届け先の名前（姓名の間のスペースを除く）

店舗名が「メイアイストア amazon店」の場合のみ、JSON形式で返してください:
{"is_amazon": true, "no": "00082345", "order_id": "249-2620196-4843868", "postal_code": "6610034", "name": "渡部奈央"}

Amazon店でない場合は:
{"is_amazon": false}"""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )
        
        try:
            result = json.loads(response.choices[0].message.content)
            if result.get('is_amazon'):
                orders.append({
                    'page': i + 1,
                    'no': result['no'],
                    'order_id': result['order_id'],
                    'postal_code': result['postal_code'].replace('-', '').replace('〒', ''),
                    'name': result['name'].replace(' ', '').replace('　', '')
                })
        except:
            pass
        
        os.remove(temp_image_path)
    
    progress_bar.empty()
    status_text.empty()
    
    return orders


def extract_shipping_label_info(pdf_path, max_pages=None):
    """送り状から情報を抽出"""
    st.info(f"📋 送り状を読み込んでいます...")
    
    images = convert_from_path(pdf_path, dpi=150)
    
    if max_pages:
        images = images[:max_pages]
    
    labels = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, image in enumerate(images):
        status_text.text(f"送り状 {i+1}/{len(images)} ページを処理中...")
        progress_bar.progress((i + 1) / len(images))
        
        temp_image_path = f"/tmp/shipping_label_page_{i+1}.jpg"
        image.save(temp_image_path, 'JPEG')
        
        base64_image = encode_image(temp_image_path)
        
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """この送り状画像から以下の情報を抽出してください:
1. お届け先の郵便番号（〒とハイフンを除く）
2. お届け先の名前（姓名の間のスペースを除く）

JSON形式で返してください:
{"postal_code": "6610034", "name": "渡部奈央"}"""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=200
        )
        
        try:
            result = json.loads(response.choices[0].message.content)
            labels.append({
                'page': i + 1,
                'postal_code': result['postal_code'].replace('-', '').replace('〒', ''),
                'name': result['name'].replace(' ', '').replace('　', '')
            })
        except:
            labels.append({
                'page': i + 1,
                'postal_code': '',
                'name': ''
            })
        
        os.remove(temp_image_path)
    
    progress_bar.empty()
    status_text.empty()
    
    return labels


def similarity(a, b):
    """文字列の類似度を計算"""
    return SequenceMatcher(None, a, b).ratio()


def match_orders_and_labels(orders, labels):
    """注文と送り状を照合"""
    st.info("🔍 注文と送り状を照合しています...")
    
    matched = []
    unmatched_orders = []
    
    for order in orders:
        best_match = None
        best_score = 0
        
        for label in labels:
            if label.get('matched'):
                continue
            
            postal_match = (order['postal_code'] == label['postal_code'])
            name_sim = similarity(order['name'], label['name'])
            
            if postal_match and name_sim > 0.8:
                score = name_sim
                if score > best_score:
                    best_score = score
                    best_match = label
        
        if best_match:
            best_match['matched'] = True
            matched.append({
                'order': order,
                'label_page': best_match['page']
            })
        else:
            unmatched_orders.append(order)
    
    return matched, unmatched_orders


def reorder_pdf(input_pdf_path, output_pdf_path, page_order):
    """PDFのページを並べ替え"""
    st.info("📄 送り状PDFを並べ替えています...")
    
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()
    
    for page_num in page_order:
        writer.add_page(reader.pages[page_num - 1])
    
    with open(output_pdf_path, 'wb') as output_file:
        writer.write(output_file)


def create_csv(data, filename):
    """CSVファイルを作成"""
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        if data:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)


# Process button
if st.button("🚀 並べ替え実行", type="primary", use_container_width=True):
    if not delivery_note_file or not shipping_label_file:
        st.error("❌ 納品書PDFと送り状PDFの両方をアップロードしてください")
    else:
        try:
            with st.spinner("処理中..."):
                # Save uploaded files
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_delivery:
                    tmp_delivery.write(delivery_note_file.read())
                    delivery_note_path = tmp_delivery.name
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_shipping:
                    tmp_shipping.write(shipping_label_file.read())
                    shipping_label_path = tmp_shipping.name
                
                # Extract information
                orders = extract_delivery_note_info(delivery_note_path)
                labels = extract_shipping_label_info(shipping_label_path)
                
                st.success(f"✅ 納品書から{len(orders)}件のAmazon注文を抽出しました")
                st.success(f"✅ 送り状から{len(labels)}件を抽出しました")
                
                # Match orders and labels
                matched, unmatched_orders = match_orders_and_labels(orders, labels)
                
                st.success(f"✅ {len(matched)}件が照合されました")
                
                if unmatched_orders:
                    st.warning(f"⚠️ {len(unmatched_orders)}件の注文に対応する送り状が見つかりませんでした")
                
                # Reorder PDF
                if matched:
                    page_order = [m['label_page'] for m in matched]
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_pdf_path = f"/tmp/sorted_labels_{timestamp}.pdf"
                    
                    reorder_pdf(shipping_label_path, output_pdf_path, page_order)
                    
                    st.success("✅ 送り状の並べ替えが完了しました")
                    
                    # Download button for sorted PDF
                    with open(output_pdf_path, 'rb') as f:
                        st.download_button(
                            label="📥 並べ替え済み送り状PDFをダウンロード",
                            data=f.read(),
                            file_name=f"sorted_labels_{timestamp}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                
                # Create unmatched CSVs
                if unmatched_orders:
                    # Sort by No.
                    unmatched_by_no = sorted(unmatched_orders, key=lambda x: x['no'])
                    csv_by_no_path = f"/tmp/missing_by_no_{timestamp}.csv"
                    create_csv(unmatched_by_no, csv_by_no_path)
                    
                    # Sort by Order ID
                    unmatched_by_order = sorted(unmatched_orders, key=lambda x: x['order_id'])
                    csv_by_order_path = f"/tmp/missing_by_order_{timestamp}.csv"
                    create_csv(unmatched_by_order, csv_by_order_path)
                    
                    st.markdown("### 📋 不一致リスト")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        with open(csv_by_no_path, 'rb') as f:
                            st.download_button(
                                label="📥 管理番号順CSVをダウンロード",
                                data=f.read(),
                                file_name=f"missing_by_no_{timestamp}.csv",
                                mime="text/csv",
                                use_container_width=True
                            )
                    
                    with col2:
                        with open(csv_by_order_path, 'rb') as f:
                            st.download_button(
                                label="📥 注文番号順CSVをダウンロード",
                                data=f.read(),
                                file_name=f"missing_by_order_{timestamp}.csv",
                                mime="text/csv",
                                use_container_width=True
                            )
                    
                    # Display unmatched orders
                    st.markdown("#### 不一致注文リスト:")
                    for order in unmatched_orders:
                        st.text(f"管理番号: {order['no']}, 注文番号: {order['order_id']}, 郵便番号: {order['postal_code']}, 名前: {order['name']}")
                
                # Cleanup
                os.remove(delivery_note_path)
                os.remove(shipping_label_path)
                
        except Exception as e:
            st.error(f"❌ エラーが発生しました: {str(e)}")

st.markdown("---")
st.markdown("Made with ❤️ by Manus AI")

