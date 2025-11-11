from typing import List, Dict, Optional, Union, Tuple
from asyncio import sleep, wrap_future
from collections import namedtuple
from dataclasses import dataclass

import pymupdf
from PyQt5 import QtCore
from PyQt5.QtGui import QPixmap


WORD = namedtuple("WORD", ["x0", "y0", "x1", "y1", "word", "block_no", "line_no", "word_no"])

@dataclass
class BLOG_INFO():
    block_point: pymupdf.Rect
    block_count: int


class XYcut():
    def __init__(self, doc:pymupdf.Document, page_no: int, first_pos: QtCore.QPoint, last_pos: QtCore.QPoint, zoom: float, img: QPixmap):
        self.doc = doc
        self.page_no = page_no
        self.first_pos = first_pos
        self.last_pos = last_pos
        self.zoom = zoom
        self.img = img
        
    def get_text_in_rect(self) -> List[WORD]:
        if self.first_pos.x() < self.last_pos.x():
            x0 = self.first_pos.x() / self.zoom
            x1 = self.last_pos.x() / self.zoom
        else:
            x0 = self.last_pos.x() / self.zoom
            x1 = self.first_pos.x() / self.zoom

        if self.first_pos.y() < self.last_pos.y():
            y0 = self.first_pos.y() / self.zoom
            y1 = self.last_pos.y() / self.zoom
        else:
            y0 = self.last_pos.y() / self.zoom
            y1 = self.first_pos.y() / self.zoom


        selection_rect = pymupdf.Rect(x0=x0, y0=y0, x1=x1, y1=y1)
        text_cordinat_list = []


        if (self.first_pos.x() < self.last_pos.x() and self.first_pos.y() < self.last_pos.y()) or (
                self.first_pos.x() > self.last_pos.x() and self.first_pos.y() > self.last_pos.y()):
            text_cordinat_list = self.select_lr(selection_rect)
        elif (self.first_pos.x() < self.last_pos.x() and self.first_pos.y() > self.last_pos.y()) or (
                self.first_pos.x() > self.last_pos.x() and self.first_pos.y() < self.last_pos.y()):
            text_cordinat_list = self.select_rl(selection_rect)
        return text_cordinat_list


    def get_blocks(self) -> Dict[int, pymupdf.Rect]:
        block_list = self.doc[self.page_no - 1].get_textpage().extractBLOCKS()
        block_dict = {}
        for b in block_list:
            block_dict[b[5]] = pymupdf.Rect(x0=b[0], y0=b[1], x1=b[2], y1=b[3])
        return block_dict

    def get_intersection_rect(self, rect1: pymupdf.Rect, rect2: pymupdf.Rect) -> Optional[pymupdf.Rect]:
        x0 = max(rect1.x0, rect2.x0)
        y0 = max(rect1.y0, rect2.y0)
        x1 = min(rect1.x1, rect2.x1)
        y1 = min(rect1.y1, rect2.y1)

        if x0 < x1 and y0 < y1:
            return pymupdf.Rect(x0=x0, y0=y0, x1=x1, y1=y1)
        else:
            # Eğer geçerli bir kesişim yoksa None döndürüyoruz
            return None

    def get_word_list(self) -> List[WORD]:
        text_page = self.doc[self.page_no - 1].get_textpage()
        word_list = text_page.extractWORDS()
        return [WORD(x0=i[0], y0=i[1], x1=i[2], y1=i[3], word=i[4], block_no=i[5], line_no=i[6], word_no=i[7]) for i in word_list]

    def detect_start_and_end_blocks(self, selection_rect: pymupdf.Rect) -> Tuple[Optional[BLOG_INFO], Optional[BLOG_INFO]]:
        start_block: Optional[BLOG_INFO] = None
        end_block: Optional[BLOG_INFO] = None

        block_dict = self.get_blocks()
        for block_count, block_point in block_dict.items():

            res = self.get_intersection_rect(selection_rect, block_point)
            if res is not None:
                if start_block is None:
                    start_block = BLOG_INFO(block_point, block_count)
                    end_block = BLOG_INFO(block_point, block_count)
                else:
                    end_block = BLOG_INFO(block_point, block_count)
        return start_block, end_block



    
    def select_lr(self, selection_rect: pymupdf.Rect) -> List[WORD]:
        start_block, end_block = self.detect_start_and_end_blocks(selection_rect)
        if start_block is None or end_block is None:
            return []
        
        word_list = self.get_word_list()

        # Secim alanini daha anlasilir olmasi icin baslangic ve bitis olarak ayir
        start_point = selection_rect.tl  # Top-Left (x0, y0)
        end_point = selection_rect.br    # Bottom-Right (x1, y1)
        
        text_cordinat_list = []
        for word in word_list:
            
            # --- 1. BLOK FİLTRESİ ---
            # Kelime, secili blok araliginin disindaysa atla
            if not (start_block.block_count <= word.block_no <= end_block.block_count):
                continue
            
            # --- 2. Y EKSENİ FİLTRESİ (Genel Dikey Eleme) ---
            # Bu, sizin hatanizi duzelten kisimdir.
            if word.block_no == start_block.block_count or  word.block_no == end_block.block_count:
            # Kelime, secim alaninin tamamen *uzerindeyse* atla
            # (Kelimenin alti, secimin ustunden daha yukarida)
                if word.block_no == start_block.block_count and word.y1 < start_point.y:
                    continue

                # Kelime, secim alaninin tamamen *altindaysa* atla
                # (Kelimenin ustu, secimin altindan daha asagida)
                if word.block_no == end_block.block_count and word.y0 > end_point.y:
                    continue

                # --- 3. X EKSENİ FİLTRESİ (Okuma Sirasi "Cut") ---
                # Bu noktada kelimenin, secim alaninin dikey bandi icinde 
                # (veya kesisim kumesinde) oldugunu biliyoruz.

                # Kelime, *baslangic satirindaysa*...
                # (Baslangic Y'si, kelimenin ust ve alt siniri arasindaysa)
                if (word.y0 <= start_point.y <= word.y1):
                    # ...ve kelime *tamamen* baslangic X'inin *solundaysa*, atla.
                    if word.x1 < start_point.x:
                        continue

                # Kelime, *bitis satirindaysa*...
                # (Bitis Y'si, kelimenin ust ve alt siniri arasindaysa)
                if (word.y0 <= end_point.y <= word.y1):
                     # ...ve kelime *tamamen* bitis X'inin *sagindaysa*, atla.
                    if word.x0 > end_point.x:
                        continue
            
            # Bu filtrelerden gecen kelime secilmistir.
            text_cordinat_list.append(word)
            
        return text_cordinat_list
    

    

    def select_rl(self, selection_rect: pymupdf.Rect) -> List[WORD]:
        start_block, end_block = self.detect_start_and_end_blocks(selection_rect)
        if start_block is None or end_block is None:
            return []
        
        word_list = self.get_word_list()

        # Secim alanini daha anlasilir olmasi icin baslangic ve bitis olarak ayir
        start_point = pymupdf.Point(x=selection_rect.x1, y=selection_rect.y0)
        end_point = pymupdf.Point(x=selection_rect.x0, y=selection_rect.y1)
        
        text_cordinat_list = []
        for word in word_list:
            
            # --- 1. BLOK FİLTRESİ ---
            # Kelime, secili blok araliginin disindaysa atla
            if not (start_block.block_count <= word.block_no <= end_block.block_count):
                continue
            
            # --- 2. Y EKSENİ FİLTRESİ (Genel Dikey Eleme) ---
            # Bu, sizin hatanizi duzelten kisimdir.
            if word.block_no == start_block.block_count or  word.block_no == end_block.block_count:
            # Kelime, secim alaninin tamamen *uzerindeyse* atla
            # (Kelimenin alti, secimin ustunden daha yukarida)
                if word.block_no == start_block.block_count and word.y1 < start_point.y:
                    continue

                # Kelime, secim alaninin tamamen *altindaysa* atla
                # (Kelimenin ustu, secimin altindan daha asagida)
                if word.block_no == end_block.block_count and word.y0 > end_point.y:
                    continue

                # --- 3. X EKSENİ FİLTRESİ (Okuma Sirasi "Cut") ---
                # Bu noktada kelimenin, secim alaninin dikey bandi icinde 
                # (veya kesisim kumesinde) oldugunu biliyoruz.

                # Kelime, *baslangic satirindaysa*...
                # (Baslangic Y'si, kelimenin ust ve alt siniri arasindaysa)
                if (word.y0 <= start_point.y <= word.y1):
                    # ...ve kelime *tamamen* baslangic X'inin *solundaysa*, atla.
                    if word.x1 < start_point.x:
                        continue

                # Kelime, *bitis satirindaysa*...
                # (Bitis Y'si, kelimenin ust ve alt siniri arasindaysa)
                if (word.y0 <= end_point.y <= word.y1):
                     # ...ve kelime *tamamen* bitis X'inin *sagindaysa*, atla.
                    if word.x0 > end_point.x:
                        continue
            
            # Bu filtrelerden gecen kelime secilmistir.
            text_cordinat_list.append(word)
            
        return text_cordinat_list
