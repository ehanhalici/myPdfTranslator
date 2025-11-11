from typing import List
import os
import re
import sys

import PyQt5
import pymupdf
from PyQt5 import QtCore
from PyQt5.QtGui import (QFont, QKeySequence, QPainter, QColor, QPixmap, QImage, QIcon,
                         QStandardItem, QFontInfo,
                         QIntValidator, QStandardItemModel, QCursor, QCloseEvent
                         )
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QShortcut, QWidget, QFrame, QVBoxLayout, QLabel,
    QFileDialog, QAction, QLineEdit,
    QComboBox)

from ui_mainwindow import Ui_window

TRANSLATE_ACTIVE = True

if TRANSLATE_ACTIVE:
    from translator_helper import translate, translate_word
else:
    def translate(sample_text: str) -> str:
        return sample_text

    def translate_word(word: str) -> str:
        return word

from x_y_cut import XYcut, WORD
    
SCREEN_DPI = 100
sys.path.append(os.path.dirname(__file__))  # for enabling python 2 like import
HOMEDIR = os.path.expanduser("~")
DEBUG = False


def debug(*args):
    if DEBUG:
        print(*args)


class Worker(QtCore.QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.fn(*self.args, **self.kwargs)
        except Exception as e:
            print(f"Exception {e}")

        return


class Translator(QtCore.QObject):
    selectionTranslateReady = QtCore.pyqtSignal()

    def __init__(self, win):
        QtCore.QObject.__init__(self)

        self.win = win

        self.already_translated = {}

    def translate_word(self, page_no: int, word: str):
        word = word.lower()
        # if word in self.already_translated.keys():
        #     return self.already_translated[word]

        word_translated = translate_word(word)

        #word_translated = re.sub('[\"\'\“\”.,:;?()\[\]\{\}]', '', word_translated)

        #self.already_translated[word] = word_translated
        return word_translated

    def translate_selection(self, text):
        self.win.selection_translated = translate(text)
        self.selectionTranslateReady.emit()

class Renderer(QtCore.QObject):
    rendered = QtCore.pyqtSignal(int, QImage)
    textFound = QtCore.pyqtSignal(int, list)

    def __init__(self, page_set=1):
        # page_set = 1 for odd, and 0 for even
        QtCore.QObject.__init__(self)
        self.doc = None
        self.page_set = page_set
        self.painter = QPainter()
        self.link_color = QColor(0, 0, 127, 40)

    def render(self, page_no, dpi):
        """ render(int, float)
        This slot takes page no. and dpi and renders that page, then emits a signal with QImage"""
        # Returns when both is true or both is false
        if page_no % 2 != self.page_set:
            return
        page = self.doc[page_no - 1]
        if not page:
            return
        img: pymupdf.Pixmap = page.get_pixmap(dpi=int(dpi))
        pix = img.samples
        stride = img.stride
        n_channels = 4 if img.alpha else 3

        # QImage formatını belirle
        if n_channels == 4:
            img_format = QImage.Format.Format_RGBA8888
        else:
            img_format = QImage.Format.Format_RGB888
        qimg = QImage(pix, img.width, img.height, stride, img_format)

        self.rendered.emit(page_no, qimg)

    def load_document(self, filename, password=''):
        """ loadDocument(str)
        Main thread uses this slot to load document for rendering """
        self.doc = pymupdf.open(filename=filename)

    def find_text(self, text, page_no, find_reverse):
        if find_reverse:
            pages = [i for i in range(1, page_no + 1)]
            pages.reverse()
        else:
            pages = [i for i in range(page_no, len(self.doc) + 1)]
        for working_page in pages:
            page: pymupdf.Page = self.doc[working_page - 1]
            text_areas = page.search_for(text, quads=True)
            if text_areas != []:
                self.textFound.emit(working_page, text_areas)
                break


class Window(QMainWindow, Ui_window):
    renderRequested = QtCore.pyqtSignal(int, float)
    loadFileRequested = QtCore.pyqtSignal(str, str)
    findTextRequested = QtCore.pyqtSignal(str, int, bool)
    
    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent)
        self.setupUi(self)
        self.dockSearch.hide()
        self.dockWidget.hide()
        self.dockWidget.setMinimumWidth(310)
        self.findTextEdit.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.treeView.setAlternatingRowColors(True)
        self.treeView.clicked.connect(self.on_outline_click)
        # resizing pages requires some time to take effect
        self.resizePageTimer = QtCore.QTimer(self)
        self.resizePageTimer.setSingleShot(True)
        self.resizePageTimer.timeout.connect(self.on_window_resize)
        # Add shortcut actions
        self.findTextAction = QAction(QIcon(":/search.png"), "Find Text", self)
        self.findTextAction.setShortcut('Ctrl+F')

        self.findTextAction.triggered.connect(self.dock_search_open_hide)
        self.outline = QAction(QIcon(":/outline.png"), "Outline", self)
        self.outline.setShortcut('Ctrl+T')
        self.outline.triggered.connect(self.dock_outline_open_hide)
        # connect menu actions signals
        self.openFileAction.triggered.connect(self.open_file)
        self.zoominAction.triggered.connect(self.zoom_in)
        self.zoomoutAction.triggered.connect(self.zoom_out)
        self.undoJumpAction.triggered.connect(self.jump_undo)
        self.prevPageAction.triggered.connect(self.go_prev_page)
        self.nextPageAction.triggered.connect(self.go_next_page)
        self.firstPageAction.triggered.connect(self.go_first_page)
        self.lastPageAction.triggered.connect(self.go_last_page)
        # Create widgets for menubar / toolbar
        self.gotoPageEdit = QLineEdit(self)
        self.gotoPageEdit.setMaximumWidth(150)
        self.gotoPageEdit.returnPressed.connect(self.go_page)
        self.gotoPageValidator = QIntValidator(1, 1, self.gotoPageEdit)
        self.gotoPageEdit.setValidator(self.gotoPageValidator)
        self.zoomLevelCombo = QComboBox(self)
        self.zoomLevelCombo.addItems(
            ["Fixed Width", "75%", "90%", "100%", "110%", "121%", "133%", "146%", "175%", "200%"])
        self.zoomLevelCombo.activated.connect(self.set_zoom)
        self.zoom_levels = [0, 75, 90, 100, 110, 121, 133, 146, 175, 200]
        # Add toolbar actions
        self.toolBar.addAction(self.openFileAction)
        self.toolBar.addSeparator()
        self.toolBar.addAction(self.outline)
        self.toolBar.addSeparator()
        self.toolBar.addAction(self.zoomoutAction)
        self.toolBar.addWidget(self.zoomLevelCombo)
        self.toolBar.addAction(self.zoominAction)
        self.toolBar.addSeparator()
        self.toolBar.addAction(self.firstPageAction)
        self.toolBar.addAction(self.prevPageAction)
        self.toolBar.addWidget(self.gotoPageEdit)
        self.toolBar.addAction(self.nextPageAction)
        self.toolBar.addAction(self.lastPageAction)
        self.toolBar.addAction(self.undoJumpAction)
        self.toolBar.addSeparator()
        self.toolBar.addAction(self.findTextAction)
        # Add widgets
        self.statusBar = QLabel(self)
        self.statusBar.setStyleSheet(
            "QLabel { "
            "font-size: 12px; "
            "border-radius: 2px; "
            "padding: 2px; "
            "background: palette(highlight); "
            "color: palette(highlighted-text); "
            "}"
        )
        self.statusBar.setMaximumHeight(16)
        self.statusBar.hide()
        # Import settings
        desktop = QApplication.desktop()
        self.settings = QtCore.QSettings("PdfTranslator", "main", self)
        self.recent_files = self.settings.value("RecentFiles", [])
        self.history_filenames = self.settings.value("HistoryFileNameList", [])
        self.history_filenames = [] if self.history_filenames is None else self.history_filenames
        self.history_page_no = self.settings.value("HistoryPageNoList", [])
        self.offset_x = int(self.settings.value("OffsetX", 4))
        self.offset_y = int(self.settings.value("OffsetY", 26))
        self.available_area = [desktop.availableGeometry().width(), desktop.availableGeometry().height()]
        self.zoomLevelCombo.setCurrentIndex(int(self.settings.value("ZoomLevel", 5)))
        # Connect Signals
        self.scrollArea.verticalScrollBar().valueChanged.connect(self.on_mouse_scroll)
        self.scrollArea.verticalScrollBar().sliderReleased.connect(self.on_slider_release)
        self.findTextEdit.returnPressed.connect(self.find_next)
        self.findNextButton.clicked.connect(self.find_next)
        self.findBackButton.clicked.connect(self.find_back)
        self.dockSearch.visibilityChanged.connect(self.dock_find_open_hide)
        # Create separate thread and move renderer to it
        self.thread1 = QtCore.QThread(self)
        self.renderer1 = Renderer(0)
        self.renderer1.moveToThread(self.thread1)  # this must be moved before connecting signals
        self.renderRequested.connect(self.renderer1.render)
        self.loadFileRequested.connect(self.renderer1.load_document)
        self.findTextRequested.connect(self.renderer1.find_text)
        self.renderer1.rendered.connect(self.set_rendered_image)
        self.renderer1.textFound.connect(self.on_text_found)
        self.thread1.start()
        self.thread2 = QtCore.QThread(self)
        self.renderer2 = Renderer(1)
        self.renderer2.moveToThread(self.thread2)
        self.renderRequested.connect(self.renderer2.render)
        self.loadFileRequested.connect(self.renderer2.load_document)
        self.renderer2.rendered.connect(self.set_rendered_image)
        self.thread2.start()
        self.thread3 = QtCore.QThread(self)
        self.translator = Translator(self)
        self.translator.moveToThread(self.thread3)
        self.translator.selectionTranslateReady.connect(self.show_selection)
        self.thread3.start()
        self.threadPool = QtCore.QThreadPool(self)
        self.threadPool.setMaxThreadCount(1)
        # copy text
        self.shortcut_copy_text = QShortcut(QKeySequence("Ctrl+C"), self)
        self.shortcut_copy_text.activated.connect(self.copy_text)
        self.shortcut_copy_translated = QShortcut(QKeySequence("Ctrl+X"), self)
        self.shortcut_copy_translated.activated.connect(self.copy_translated)
        # Initialize Variables
        self.doc: pymupdf.Document = None
        self.filename = ''
        self.password = ''
        self.pages = []
        self.pages_count = 0
        self.rendered_pages = []
        self.current_page = 1
        self.jumped_from = None
        self.max_preload = 1
        self.scroll_render_lock = False
        self.frame = None
        self.verticalLayout = None
        self.search_text = ""
        self.search_result_page = 0
        self.text = {}
        self.text_rect = {}
        self.text_translated = {}
        self.selection_translated = ""
        self.selection_text = ""
        self.popup = None
        self.active_word = {
            "page": None,
            "count": None
        }
        self.selection_text_cordinat = []
        self.popup_move_x = 0
        self.popup_move_y = 0
        self.painter = None
        self.dock_search_status = False
        self.dock_widget_status = False
        # Show Window
        width = int(self.settings.value("WindowWidth", 1040))
        height = int(self.settings.value("WindowHeight", 717))
        self.resize(width, height)
        #self.load_pdf("/home/emrehan/downloads/mixbox.pdf") ## todo kapat
        self.show()

    # ------------------------- Pdf Loading

    def open_file(self):
        filename, sel_filter = QFileDialog.getOpenFileName(self,
                                                           "Select Document to Open", self.filename,
                                                           "Portable Document Format (*.pdf);;All Files (*)")
        if filename != "":
            self.load_pdf(filename)

    def load_pdf(self, filename):
        """ Loads pdf document in all threads """
        filename = os.path.expanduser(filename)
        doc = pymupdf.open(filename)
        if not doc:
            return
        password = ''

        self.remove_old_doc()

        self.doc = doc
        self.filename = filename
        self.pages_count = self.doc.page_count
        self.current_page = 1
        self.rendered_pages = []
        self.get_outlines(self.doc)
        # Load Document in other threads
        self.loadFileRequested.emit(self.filename, password)
        if collapse_user(self.filename) in self.history_filenames:
            self.current_page = int(self.history_page_no[self.history_filenames.index(collapse_user(self.filename))])
        self.current_page = min(self.current_page, self.pages_count)
        self.scroll_render_lock = False
        # Show/Add widgets
        self.frame = Frame(self.scrollAreaWidgetContents)
        self.verticalLayout = QVBoxLayout(self.frame)
        self.horizontalLayout_2.addWidget(self.frame)
        self.scrollArea.verticalScrollBar().setValue(0)
        self.frame.jumpToRequested.connect(self.jump_page)
        self.frame.getWordOnMouseRequested.connect(self.get_word_on_mouse)
        self.frame.selectLineRequested.connect(self.select_line)
        self.frame.unselectLineRequest.connect(self.unselect_line)
        self.frame.calcSelectLineRequested.connect(self.clac_select_line_text)
        self.frame.sendSelectionToTranslateRequest.connect(self.send_selection_to_translate)
        self.frame.showStatusRequested.connect(self.show_status)

        # Render 4 pages, (Preload 3 pages)
        self.max_preload = min(4, self.pages_count)
        # Add pages
        for i in range(self.pages_count):
            page = PageWidget(i + 1, self.frame)
            self.verticalLayout.addWidget(page, 0, QtCore.Qt.AlignCenter)
            self.pages.append(page)
        self.resize_pages()
        self.gotoPageEdit.setPlaceholderText(str(self.current_page) + " / " + str(self.pages_count))
        self.gotoPageValidator.setTop(self.pages_count)
        self.setWindowTitle(os.path.basename(self.filename) + " - PdfTranslator")
        if self.current_page != 1:
            QtCore.QTimer.singleShot(150 + self.pages_count // 3, self.jump_current_page)

    def remove_old_doc(self):
        if not self.doc:
            return
        # Save current page number
        # self.save_file_data()
        # Remove old document
        for i in range(len(self.pages)):
            self.verticalLayout.removeWidget(self.pages[-1])
        for i in range(len(self.pages)):
            self.pages.pop().deleteLater()
        self.frame.deleteLater()
        self.jumped_from = None

    # ------------------------- Rendering

    def set_rendered_image(self, page_no, image):
        # takes a QImage and sets pixmap of the specified page
        # when number of rendered pages exceeds a certain number, old page image is
        # deleted to save memory
        debug("Set Rendered Image :", page_no)
        self.pages[page_no - 1].set_page_data(page_no, QPixmap.fromImage(image), self.doc[page_no - 1])
        # Request to render next page
        if self.current_page <= page_no < (self.current_page + self.max_preload - 2):
            if (page_no + 2 not in self.rendered_pages) and (page_no + 2 <= self.pages_count):
                self.rendered_pages.append(page_no + 2)
                self.renderRequested.emit(page_no + 2, self.pages[page_no + 1].dpi)
        # Replace old rendered pages with blank image
        if len(self.rendered_pages) > 10:
            cleared_page_no = self.rendered_pages.pop(0)
            debug("Clear Page :", cleared_page_no)
            self.pages[cleared_page_no - 1].clear()
        debug("Rendered Pages :", self.rendered_pages)
        debug("current_page :", self.current_page)
        debug("page_no :", page_no)
        text_info_list: str = self.doc[page_no - 1].get_text("words")
        send_text_to_translation = []
        self.text[page_no - 1] = []
        self.text_rect[page_no - 1] = []
        self.text_translated[page_no - 1] = []
        for i in text_info_list:
            self.text[page_no - 1].append(i[4])
            self.text_translated[page_no - 1].append(i[4])
            send_text_to_translation.append(i[4])
            self.text_rect[page_no - 1].append(i[0:4])

    def render_current_page(self):
        # Requests to render current page. if it is already rendered, then request
        # to render next unrendered page
        requested = 0
        for page_no in range(self.current_page, self.current_page + self.max_preload):
            if (page_no not in self.rendered_pages) and (page_no <= self.pages_count):
                self.rendered_pages.append(page_no)
                self.renderRequested.emit(page_no, self.pages[page_no - 1].dpi)
                requested += 1
                debug("Render Requested :", page_no)
                if requested == 2:
                    return

    # ------------------------- Moving On Pages

    def on_mouse_scroll(self, pos):
        # It is called when vertical scrollbar value is changed.
        # Get the current page number on scrolling, then requests to render
        index = self.verticalLayout.indexOf(self.frame.childAt(int(self.frame.width() / 2), pos))
        if index == -1:
            return
        self.gotoPageEdit.setPlaceholderText(str(index + 1) + " / " + str(self.pages_count))
        if self.scrollArea.verticalScrollBar().isSliderDown() or self.scroll_render_lock:
            return
        self.current_page = index + 1
        self.render_current_page()

    def on_slider_release(self):
        self.on_mouse_scroll(self.scrollArea.verticalScrollBar().value())

    def jump_current_page(self):
        """ this is used as a slot, to connect with a timer"""
        self.jump_page(self.current_page)

    def jump_page(self, page_num, top=0.0):
        """ scrolls to a particular page and position """
        if page_num < 1:
            page_num = 1
        elif page_num > self.pages_count:
            page_num = self.pages_count
        if not (0 < top < 1.0):
            top = 0
        self.jumped_from = self.current_page
        self.current_page = page_num
        scrollbar_pos = self.pages[page_num - 1].pos().y()
        scrollbar_pos += top * self.pages[page_num - 1].height()
        self.scrollArea.verticalScrollBar().setValue(int(scrollbar_pos))

    def jump_undo(self):
        if self.jumped_from is None:
            return
        self.jump_page(self.jumped_from)

    def go_next_page(self):
        if self.current_page == self.pages_count:
            return
        self.jump_page(self.current_page + 1)

    def go_prev_page(self):
        if self.current_page == 1:
            return
        self.jump_page(self.current_page - 1)

    def go_first_page(self):
        self.jump_page(1)

    def go_last_page(self):
        self.jump_page(self.pages_count)

    def go_page(self):
        text = self.gotoPageEdit.text()
        if text == "":
            return
        self.jump_page(int(text))
        self.gotoPageEdit.clear()
        self.gotoPageEdit.clearFocus()

    # -------------------------  Zoom and Size Management

    def get_available_width(self):
        # Returns available width for rendering a page
        dock_width = 0 if self.dockWidget.isHidden() else self.dockWidget.width()
        return self.width() - dock_width - 50

    def resize_pages(self):
        # Resize all pages according to zoom level
        page_dpi = self.zoom_levels[self.zoomLevelCombo.currentIndex()] * SCREEN_DPI / 100
        fixed_width = self.get_available_width()
        for i in range(self.pages_count):
            pg_width = self.doc[i].rect.width  # width in points
            pg_height = self.doc[i].rect.height
            if self.zoomLevelCombo.currentIndex() == 0:  # if fixed width
                dpi = 72.0 * fixed_width / pg_width
            else:
                dpi = page_dpi
            self.pages[i].dpi = dpi
            self.pages[i].setFixedSize(int(pg_width * dpi / 72.0), int(pg_height * dpi / 72.0))
        for page_no in self.rendered_pages:
            self.pages[page_no - 1].clear()
        self.rendered_pages = []
        # self.translator.already_translated = []
        self.render_current_page()

    def resizeEvent(self, ev):
        QMainWindow.resizeEvent(self, ev)
        if self.filename == '': return
        if self.zoomLevelCombo.currentIndex() == 0:
            self.resize_page_timer.start(200)

    def on_window_resize(self):
        for i in range(self.pages_count):
            self.pages[i].annots_listed = False  # Clears prev link annotation positions
        self.resize_pages()
        wait(300)
        self.jump_current_page()
        if not self.isMaximized():
            self.settings.setValue("WindowWidth", self.width())
            self.settings.setValue("WindowHeight", self.height())

    def set_zoom(self, index):
        """ Gets called when zoom level is changed"""
        self.scroll_render_lock = True  # rendering on scroll is locked as set scroll position
        self.resize_pages()
        QtCore.QTimer.singleShot(300, self.zoom_after)

    def zoom_in(self):
        index = self.zoomLevelCombo.currentIndex()
        if index == len(self.zoom_levels) - 1: return
        if index == 0: index = 3
        self.zoomLevelCombo.setCurrentIndex(index + 1)
        self.set_zoom(index + 1)

    def zoom_out(self):
        index = self.zoomLevelCombo.currentIndex()
        if index == 1: return
        if index == 0: index = 4
        self.zoomLevelCombo.setCurrentIndex(index - 1)
        self.set_zoom(index - 1)

    def zoom_after(self):
        scrollbar_pos = self.pages[self.current_page - 1].pos().y()
        self.scrollArea.verticalScrollBar().setValue(scrollbar_pos)
        self.scroll_render_lock = False

    # ------------------------- Search Text

    def dock_search_open_hide(self):
        if not self.dock_search_status:
            self.dockSearch.show()
        else:
            self.dockSearch.hide()
        self.dock_search_status = not self.dock_search_status

    def dock_find_open_hide(self, enable):
        if enable:
            self.findTextEdit.setText('')
            self.findTextEdit.setFocus()
            self.search_text = ''
            self.search_result_page = 0
        elif self.search_result_page != 0:
            self.pages[self.search_result_page - 1].highlight_area = None
            self.pages[self.search_result_page - 1].update_image()

    def find_next(self):
        """ search text in current page and next pages """
        text = self.findTextEdit.text()
        if text == "":
            return
        # search from current page when text changed
        if self.search_text != text or self.search_result_page == 0:
            search_from_page = self.current_page
        else:
            search_from_page = self.search_result_page + 1
        self.findTextRequested.emit(text, search_from_page, False)
        if self.search_result_page != 0:  # clear previous highlights
            self.pages[self.search_result_page - 1].highlight_area = None
            self.pages[self.search_result_page - 1].update_image()
            self.search_result_page = 0
        self.search_text = text

    def find_back(self):
        """ search text in pages before current page """
        text = self.findTextEdit.text()
        if text == "":
            return
        if self.search_text != text or self.search_result_page == 0:
            search_from_page = self.current_page
        else:
            search_from_page = self.search_result_page - 1
        self.findTextRequested.emit(text, search_from_page, True)
        if self.search_result_page != 0:
            self.pages[self.search_result_page - 1].highlight_area = None
            self.pages[self.search_result_page - 1].update_image()
            self.search_result_page = 0
        self.search_text = text

    def on_text_found(self, page_no, areas):
        self.pages[page_no - 1].highlight_area = areas
        self.search_result_page = page_no
        if self.pages[page_no - 1].pixmap():
            self.pages[page_no - 1].update_image()
        first_result_pos = areas[0].rect.y0 / self.doc[page_no - 1].rect.height
        self.jump_page(page_no, first_result_pos)

    # ------------------------- Translation Interface

    def get_word_on_mouse(self, page_no, pos):
        zoom = self.pages[page_no - 1].height() / self.doc[page_no - 1].rect.height

        active_word_count = -1

        for rect, count in zip(self.text_rect[page_no - 1], range(len(self.text_rect[page_no - 1]))):
            if self.is_point_in_rect(rect, pos, zoom):
                active_word_count = count
                self.create_word_popup_location(rect, pos, zoom)
                break

        if self.active_word["page"] == page_no and self.active_word["count"] == active_word_count:
            return

        elif active_word_count != -1:
            self.active_word["page"] = page_no
            self.active_word["count"] = active_word_count
            t = self.translator.translate_word(page_no, self.text_translated[page_no - 1][active_word_count])

            self.build_popup(t, "window")

        else:
            try:
                self.kill_popup()
                self.active_word["page"] = None
                self.active_word["count"] = None
            except:
                pass

    def is_point_in_rect(self, rect, pos, zoom):
        if pos.x() / zoom >= rect[0]:
            if pos.y() / zoom >= rect[1]:
                if pos.x() / zoom <= rect[2]:
                    if pos.y() / zoom <= rect[3]:
                        return True
        return False

    def create_word_popup_location(self, rect, pos, zoom):
        mouse_x = pos.x() / zoom
        self.popup_move_x = int((rect[0] - mouse_x) * zoom)
        mouse_y = pos.y() / zoom
        self.popup_move_y = int(
            (mouse_y - (rect[1] - ((rect[3] - rect[1]) + QFontInfo(QFont("times", 1)).pointSize()))) ) * zoom

    def clac_select_line_text(self, page_no, first_pos, last_pos, img, rect_zoom):
        zoom = self.pages[page_no - 1].height() / self.doc[page_no - 1].rect.height
        if last_pos.y() < first_pos.y():
            upper_pos = last_pos / zoom
            lower_pos = first_pos / zoom
        else:
            upper_pos = first_pos / zoom
            lower_pos = last_pos / zoom

        text_page = self.doc[page_no - 1].get_textpage()
        text = text_page.extractSelection(pointa=(upper_pos.x(), upper_pos.y()), pointb=(lower_pos.x(), lower_pos.y()))

        self.selection_translated = text
        self.selection_text = text.replace("\n", '')
        

    def select_line(self, page_no, pos, first_pos, img, rect_zoom):
        zoom = self.pages[page_no - 1].height() / self.doc[page_no - 1].rect.height
        self.painter = QPainter(img)

        xyCut = XYcut(doc=self.doc, page_no=page_no, first_pos=first_pos, last_pos=pos, zoom=rect_zoom, img=img)
        text_cordinat_list: List[WORD] = xyCut.get_text_in_rect()
        for text_cordinat in text_cordinat_list:
            self.painter.fillRect(int(text_cordinat.x0 * zoom),
                                  int(text_cordinat.y0 * zoom),
                                  int((text_cordinat.x1 - text_cordinat.x0) *zoom),
                                  int((text_cordinat.y1 - text_cordinat.y0) *zoom),
                                  QColor(100, 100, 100, 100))

        self.create_selected_line_popup_location(self.selection_text_cordinat, pos, zoom)
        self.painter.end()
        self.pages[page_no - 1].setPixmap(img)

    def create_selected_line_popup_location(self, rects, pos, zoom):
        if not rects:
            return
        mouse_x = pos.x() / zoom
        mouse_y = pos.y() / zoom

        min_x_in_line = rects[0][0]
        max_y_in_line = 0
        for rect in rects:
            if rect[0] < min_x_in_line:
                min_x_in_line = rect[0]
            if rect[3] > max_y_in_line:
                max_y_in_line = rect[3]

        self.popup_move_x = int((min_x_in_line - mouse_x) * zoom)
        self.popup_move_y = int((max_y_in_line - mouse_y) * zoom)

    def unselect_line(self, page_no, img):
        self.painter = QPainter(img)
        self.pages[page_no - 1].setPixmap(img)
        self.painter.end()
        self.selection_text = ""
        self.selection_translated = ""
        self.selection_text_cordinat.clear()

    def send_selection_to_translate(self):
        if self.selection_translated == "":
            return
        worker = Worker(self.translator.translate_selection, self.selection_translated)
        self.threadPool.start(worker)

    def show_selection(self):
        self.build_popup(self.selection_translated, "popup")

    def build_popup(self, name, win_type):
        geometry = {"x": QCursor().pos().x() + self.popup_move_x,
                    "y": QCursor().pos().y() + self.popup_move_y}
        self.popup = Popup(name, win_type, geometry)
        self.popup.adjustSize()
        self.popup.show()

    def kill_popup(self):
        self.popup.close()


    # ------------------------- Outlines TODO

    def dock_outline_open_hide(self):
        if not self.dock_widget_status:
            self.dockWidget.show()
        else:
            self.dockWidget.hide()
        self.dock_widget_status = not self.dock_widget_status

    def get_outlines(self, doc):
        outlines = doc.get_toc()
        if not outlines:
            return

        outline_model = QStandardItemModel(self)
        parent_item = outline_model.invisibleRootItem()
        q_item_dict = {
            "0": parent_item
        }
        for item in outlines:
            level, title, page_number = item
            item = QStandardItem(title)

            item.setData(page_number, QtCore.Qt.UserRole + 1)
            item.setData(0, QtCore.Qt.UserRole + 2)
            page_item = item.clone()
            page_item.setText(str(page_number))
            page_item.setTextAlignment(QtCore.Qt.AlignRight)
            q_item_dict[str(level - 1)].appendRow([item, page_item])
            q_item_dict[str(level)] = item

        self.treeView.setModel(outline_model)
        self.treeView.setHeaderHidden(True)
        self.treeView.header().setSectionResizeMode(0, 1)
        self.treeView.header().setStretchLastSection(False)

    def on_outline_click(self, m_index):
        page_num = self.treeView.model().data(m_index, QtCore.Qt.UserRole + 1)
        top = self.treeView.model().data(m_index, QtCore.Qt.UserRole + 2)
        if not page_num: return
        self.jump_page(page_num, top)

    # ------------------------- Other Functions

    def copy_text(self):
        QApplication.clipboard().setText(self.selection_text)

    def copy_translated(self):
        QApplication.clipboard().setText(self.selection_translated)

    def show_status(self, url):
        if url == "":
            self.statusBar.hide()
            return
        self.statusBar.setText(url)
        self.statusBar.adjustSize()
        self.statusBar.move(0, self.height() - self.statusBar.height())
        self.statusBar.show()

    # ------------------------- Quit

    def save_file_data(self):
        if self.filename != '':
            filename = collapse_user(self.filename)
            if filename in self.history_filenames:
                index = self.history_filenames.index(filename)
                self.history_page_no[index] = self.current_page
            else:
                self.history_filenames.insert(0, filename)
                self.history_page_no.insert(0, self.current_page)
            if filename in self.recent_files:
                self.recent_files.remove(filename)
            self.recent_files.insert(0, filename)

    def closeEvent(self, ev):
        """ Save all settings on window close """
        return QMainWindow.closeEvent(self, ev)
        # # self.save_file_data()
        # self.settings.setValue("OffsetX", self.geometry().x() - self.x())
        # self.settings.setValue("OffsetY", self.geometry().y() - self.y())
        # self.settings.setValue("ZoomLevel", self.zoomLevelCombo.currentIndex())
        # self.settings.setValue("HistoryFileNameList", self.history_filenames[:100])
        # self.settings.setValue("HistoryPageNoList", self.history_page_no[:100])
        # self.settings.setValue("RecentFiles", self.recent_files[:10])
        # return QMainWindow.closeEvent(self, ev)

    def on_quit(self):
        return QMainWindow.closeEvent(self, QCloseEvent())


class Frame(QFrame):
    """ This widget is a container of PageWidgets. PageWidget communicates
        Window through this widget """
    jumpToRequested = QtCore.pyqtSignal(int, float)
    getWordOnMouseRequested = QtCore.pyqtSignal(int, QtCore.QPoint)
    selectLineRequested = QtCore.pyqtSignal(int, QtCore.QPoint, QtCore.QPoint, QPixmap, float)
    unselectLineRequest = QtCore.pyqtSignal(int, QPixmap)
    calcSelectLineRequested = QtCore.pyqtSignal(int, QtCore.QPoint, QtCore.QPoint, QPixmap, float)
    sendSelectionToTranslateRequest = QtCore.pyqtSignal()
    showStatusRequested = QtCore.pyqtSignal(str)

    # parent is scrollAreaWidgetContents
    def __init__(self, parent):
        QFrame.__init__(self, parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

    def jump_page(self, page_num, top):
        self.jumpToRequested.emit(page_num, top)

    def get_word_on_mouse(self, page_num, pos):
        debug(pos)
        self.getWordOnMouseRequested.emit(page_num, pos)

    def select_line(self, page_num, pos, first_pos, img, rect_zoom):
        self.selectLineRequested.emit(page_num, pos, first_pos, img, rect_zoom)

    def calc_select_line(self, page_num, first_pos, last_pos, img, rect_zoom):
        self.calcSelectLineRequested.emit(page_num, first_pos, last_pos, img, rect_zoom)

    def unselect_line(self, page_no, img):
        self.unselectLineRequest.emit(page_no, img)

    def send_selection_to_translate(self):
        self.sendSelectionToTranslateRequest.emit()

    def show_status(self, msg):
        self.showStatusRequested.emit(msg)


class PageWidget(QLabel):
    """ This widget shows a rendered page """

    def __init__(self, page_num, frame=None):
        QLabel.__init__(self, frame)
        self.manager = frame
        self.setMouseTracking(True)
        self.setSizePolicy(0, 0)
        self.link_areas = []
        self.link_annots = []
        self.annots_listed = False
        self.highlight_area = None
        self.page_num = page_num
        self.image = QPixmap()
        self.selectMode = False
        self.mousePressPos = None

    def set_page_data(self, page_no, pixmap, page):
        self.image = pixmap
        self.update_image()

    def clear(self):
        QLabel.clear(self)
        self.image = QPixmap()

    def mouseMoveEvent(self, ev):
        if self.selectMode:
            img = self.image.copy()
            rect_zoom = self.dpi / 72.0
            self.manager.select_line(self.page_num, ev.pos(), self.mousePressPos, img, rect_zoom)

        else:
            self.manager.get_word_on_mouse(self.page_num, ev.pos())
            self.manager.show_status("")
            self.unsetCursor()
        ev.ignore()  # pass to underlying frame if not over link or copy text mode

    def mousePressEvent(self, ev):
        self.manager.unselect_line(self.page_num, self.image.copy())
        self.selectMode = True
        self.mousePressPos = ev.pos()
        ev.ignore()

    def mouseReleaseEvent(self, ev):
        if self.selectMode:
            img = self.image.copy()
            rect_zoom = self.dpi / 72.0
            self.manager.calc_select_line(self.page_num, self.mousePressPos, ev.pos(), img, rect_zoom)

        self.selectMode = False
        self.mousePressPos = None
        self.manager.send_selection_to_translate()
        ev.ignore()

    def update_image(self):
        """ repaint page widget, and draw highlight areas """
        if self.highlight_area:
            img = self.image.copy()
            painter = QPainter(img)
            zoom = self.dpi / 72.0
            for area in self.highlight_area:
                box = QtCore.QRectF(area.rect.x0 * zoom, area.rect.y0 * zoom,
                                    area.rect.width * zoom, area.rect.height * zoom)
                painter.fillRect(box, QColor(0, 255, 0, 127))
            painter.end()
            self.setPixmap(img)
        else:
            self.setPixmap(self.image)


class Popup(QWidget):
    def __init__(self, name, win_type, win_pos):
        super().__init__()
        self.name = name
        self.lbl = QLabel(self.name, self)
        self.lbl.setFont(QFont("times", 16))
        self.setFont(QFont("times", 16))
        self.lbl.setStyleSheet("QWidget { background-color : white; color : #000099; }")
        self.lbl.setWordWrap(True)
        self.lbl.adjustSize()

        if win_type == "window":
            self.setWindowFlags(PyQt5.QtCore.Qt.CustomizeWindowHint)
        elif win_type == "popup":
            self.setWindowFlags(PyQt5.QtCore.Qt.Popup)
        self.setGeometry(int(win_pos["x"]), int(win_pos["y"]), 0, 0)


def wait(millisecond):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(millisecond, loop.quit)
    loop.exec_()


def collapse_user(path):
    # converts /home/user/file.ext to ~/file.ext
    if path.startswith(HOMEDIR):
        return path.replace(HOMEDIR, '~', 1)
    return path


def elide_middle(text, length):
    if len(text) <= length: return text
    return text[:length // 2] + '...' + text[len(text) - length + length // 2:]


def main():
    app = QApplication(sys.argv)
    win = Window()
    if len(sys.argv) > 1 and os.path.exists(os.path.abspath(sys.argv[-1])):
        win.load_pdf(os.path.abspath(sys.argv[-1]))
    app.aboutToQuit.connect(win.on_quit)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
