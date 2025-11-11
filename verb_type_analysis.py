import spacy
from collections import Counter

# spaCy dil modelini yükle
nlp = spacy.load("en_core_web_trf")

# Zamanları tespit etmek için yarbddımcı fonksiyon
def detect_tense(sentence):
    doc = nlp(sentence)
    tenses = []
    
    for token in doc:
        if token.pos_ == 'VERB':
            # Morph özelliklerine göre zaman tespiti
            if 'Tense=Past' in token.morph:
                tenses.append('simple past')
            elif 'Tense=Pres' in token.morph:
                tenses.append('simple present')
            elif 'Tense=Fut' in token.morph:
                tenses.append('simple future')
            else:
                tenses.append("unknow")
    
    return tenses

# Dosyadan cümleleri oku
def analyze_text_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    input_text = text.strip()
    doc = nlp(input_text.replace("\n", " "))
    sentences = [sent.text for sent in doc.sents]
    total_sentences = len(sentences)
    tense_counter = Counter()

    for sentence in sentences:
        tenses = detect_tense(sentence.strip())
        if tenses:
            tense_counter.update(tenses)

    print(f"Toplam cümle sayısı: {total_sentences} adet.")
    for tense, count in tense_counter.items():
        print(f"{tense} cümle sayısı: {count} adet.")

# Kullanım
file_path = "/home/emrehan/kod/try/pdfTrans/deneme.txt"
analyze_text_file(file_path)
