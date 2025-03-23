import kivy
kivy.require('2.2.1')
from kivy.logger import Logger
Logger.setLevel('DEBUG')
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.metrics import dp
import threading
from kivy.utils import platform
from google.cloud import texttospeech
import logging
import shutil
from jnius import PythonJavaClass, java_method
logging.basicConfig(level=logging.DEBUG)


GOOGLE_TTS_AVAILABLE = False  # Google TTS 비활성화
if platform != 'android':
    from gtts import gTTS

import tempfile
from kivy.uix.spinner import Spinner
from kivy.graphics import Color, Rectangle
from kivy.uix.widget import Widget
import time
import json
import os
import re
from kivy.core.audio import SoundLoader
from kivy.core.text import LabelBase
from kivy.config import Config
Config.set('kivy', 'kivy_copy_default_data', '0')
from kivy.resources import resource_add_path

# Android 플랫폼 관련 설정
if platform == 'android':
    try:
        from jnius import autoclass, PythonJavaClass, java_method
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        Locale = autoclass('java.util.Locale')
        TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
    except ImportError:
        class DummyClass:
            pass
        PythonActivity = DummyClass()
        activity = None
        Locale = DummyClass()
        TextToSpeech = DummyClass()
else:
    try:
        from gtts import gTTS
    except ImportError:
        print("TTS 라이브러리를 설치하세요: pip install gtts")

def get_app_directory():
    if platform == 'android':
        # 내부 저장소 사용
        app = App.get_running_app()
        return os.path.join(app.user_data_dir, 'FlashcardApp')
    return os.getcwd()

def setup_fonts(app_instance=None):
    if platform == 'android' and app_instance:
        base_path = app_instance.user_data_dir  # Android 내부 저장소 사용
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))  # 소스 디렉토리 기준
    font_path = os.path.join(base_path, 'fonts')
    os.makedirs(font_path, exist_ok=True)
    nanum_gothic_regular = os.path.join(font_path, 'NanumGothic-Regular.ttf')
    nanum_gothic_bold = os.path.join(font_path, 'NanumGothic-Bold.ttf')
    
    if not os.path.exists(nanum_gothic_regular) or not os.path.exists(nanum_gothic_bold):
        print(f"폰트 파일이 없습니다: {nanum_gothic_regular}, {nanum_gothic_bold}")
        return False
    
    resource_add_path(font_path)
    try:
        LabelBase.register(name='NanumGothic', fn_regular=nanum_gothic_regular, fn_bold=nanum_gothic_bold)
        Config.set('kivy', 'default_font', ['NanumGothic', nanum_gothic_regular, nanum_gothic_bold])
        Window.font_name = 'NanumGothic'
        return True
    except Exception as e:
        print(f"폰트 설정 오류: {e}")
        return False

# TTS 초기화 리스너
class TTSInitListener(PythonJavaClass):
    __javainterfaces__ = ['android.speech.tts.TextToSpeech$OnInitListener']
    def __init__(self, app):
        super().__init__()
        self.app = app
    @java_method('(I)V')
    def onInit(self, status):
        if status == TextToSpeech.SUCCESS:
            logging.debug("TTS 초기화 성공")
            self.app.tts_initialized = True
        else:
            logging.error(f"TTS 초기화 실패: 상태 코드 {status}")
            self.app.tts_initialized = False

def get_app_directory():
    if platform == 'android':
        app = App.get_running_app()
        return os.path.join(app.user_data_dir, 'FlashcardApp')
    return os.getcwd()

def setup_fonts(app_instance=None):
    if platform == 'android':
        try:
            from kivy.core.text import LabelBase
            from kivy.config import Config
            from kivy.core.window import Window
            LabelBase.register(name='NotoSans',
                              fn_regular='/system/fonts/NotoSans-Regular.ttf',
                              fn_bold='/system/fonts/NotoSans-Bold.ttf')
            Config.set('kivy', 'default_font', ['NotoSans', '/system/fonts/NotoSans-Regular.ttf', '/system/fonts/NotoSans-Bold.ttf'])
            Window.font_name = 'NotoSans'
            logging.debug("Noto Sans 폰트 설정 완료")
            return True
        except Exception as e:
            logging.error(f"Noto Sans 폰트 설정 오류: {e}")
            return False
    return False

def ensure_kivy_config_dir():
    """Kivy 설정 디렉토리 생성 및 권한 확인"""
    kivy_dir = os.path.join(get_app_directory(), '.kivy')
    icon_dir = os.path.join(kivy_dir, 'icon')
    try:
        if not os.path.exists(kivy_dir):
            os.makedirs(kivy_dir, exist_ok=True)
            logging.debug(f"Kivy 디렉토리 생성: {kivy_dir}")
        if not os.path.exists(icon_dir):
            os.makedirs(icon_dir, exist_ok=True)
            logging.debug(f"Icon 디렉토리 생성: {icon_dir}")
        else:
            # 기존 디렉토리가 있으면 권한 수정 시도
            os.chmod(icon_dir, 0o775)  # 읽기/쓰기/실행 권한 부여
            logging.debug(f"Icon 디렉토리 권한 수정: {icon_dir}")
    except Exception as e:
        logging.error(f"Kivy 디렉토리 설정 오류: {e}")

class FlashcardApp(App):
    def __init__(self):
        super().__init__()
        self.tts_engine = None
        self.tts_initialized = False
        if platform == 'android':
            self.init_android_tts()

    def init_android_tts(self):
        try:
            logging.debug("TTS 초기화 시도")
            self.tts_engine = TextToSpeech(activity, TTSInitListener(self))
            for _ in range(50):
                if self.tts_initialized:
                    logging.debug("TTS 초기화 완료")
                    break
                import time
                time.sleep(0.1)
            if not self.tts_initialized:
                logging.error("TTS 초기화 시간 초과")
        except Exception as e:
            logging.error(f"TTS 초기화 중 예외 발생: {e}")

    def init_google_tts(self):
        if platform != 'android':
            try:
                self.tts_client = texttospeech.TextToSpeechClient()
                print("Google Cloud TTS 초기화 성공")
            except Exception as e:
                print(f"Google Cloud TTS 초기화 실패: {e}")
                self.tts_client = None
        else:
            self.tts_client = None  # 안드로이드에서는 사용 안 함

    def build(self):
            logging.debug("build 메서드 시작")
            self.app_dir = get_app_directory()
            logging.debug(f"앱 디렉토리: {self.app_dir}")
            if not os.path.exists(self.app_dir):
                os.makedirs(self.app_dir, exist_ok=True)
                logging.debug(f"디렉토리 생성: {self.app_dir}")
            ensure_kivy_config_dir()  # Kivy 디렉토리 설정 추가
            if not setup_fonts(self):
                logging.warning("폰트 설정 실패, 기본 폰트로 진행")
            logging.debug("ScreenManager 초기화 시작")
            self.sm = ScreenManager()
            logging.debug("화면 추가 시작")
            self.sm.add_widget(MainScreen(name='main'))
            self.sm.add_widget(AddCardScreen(name='add_card'))
            self.sm.add_widget(BulkAddScreen(name='bulk_add'))
            self.sm.add_widget(FlashcardScreen(name='flashcard'))
            self.sm.add_widget(ExcelScreen(name='excel'))
            self.sm.add_widget(DeckSelectionScreen(name='deck_selection'))
            logging.debug("build 메서드 완료")
            return self.sm

    def load_cards(self):
        if self.current_deck:
            deck_dir = os.path.join(self.app_dir, 'decks', self.current_deck)
            file_path = os.path.join(deck_dir, 'flashcards.json')
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.cards = json.load(f)
                print(f"불러온 카드 수: {len(self.cards)}")
            except FileNotFoundError:
                self.cards = []
            except json.JSONDecodeError:
                self.cards = []
                self.show_popup("오류", "카드 파일이 손상되었습니다.")

    def save_cards(self):
        if self.current_deck:
            deck_dir = os.path.join(self.app_dir, 'decks', self.current_deck)
            file_path = os.path.join(deck_dir, 'flashcards.json')
            try:
                os.makedirs(deck_dir, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.cards, f, ensure_ascii=False, indent=2)
                print(f"카드가 저장되었습니다: {len(self.cards)}개")
            except Exception as e:
                self.show_popup("오류", f"카드 저장 실패: {str(e)}")

    def show_popup(self, title, message):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        popup = Popup(title=title, content=Label(text=message, font_name=font_path), size_hint=(0.7, 0.3))
        popup.open()

class MainScreen(Screen):
    def __init__(self, app_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.app_dir = app_dir or get_app_directory()
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        layout = BoxLayout(orientation='vertical')
        layout.add_widget(Button(text='플래시카드 추가', font_name=font_path, on_press=self.go_to_add_card))
        layout.add_widget(Button(text='일괄 추가', font_name=font_path, on_press=self.go_to_bulk_add))
        layout.add_widget(Button(text='플래시카드 모드', font_name=font_path, on_press=self.go_to_flashcard))
        layout.add_widget(Button(text='엑셀 모드', font_name=font_path, on_press=self.go_to_excel))
        layout.add_widget(Button(text='단어장 제목 선택', font_name=font_path, on_press=self.go_to_deck_selection))
        self.add_widget(layout)

    def go_to_add_card(self, instance):
        if App.get_running_app().current_deck:
            self.manager.current = 'add_card'
        else:
            App.get_running_app().show_popup("알림", "단어장을 먼저 선택하세요.")

    def go_to_bulk_add(self, instance):
        if App.get_running_app().current_deck:
            self.manager.current = 'bulk_add'
        else:
            App.get_running_app().show_popup("알림", "단어장을 먼저 선택하세요.")

    def go_to_flashcard(self, instance):
        if App.get_running_app().current_deck:
            self.manager.current = 'flashcard'
        else:
            App.get_running_app().show_popup("알림", "단어장을 먼저 선택하세요.")

    def go_to_excel(self, instance):
        if App.get_running_app().current_deck:
            self.manager.current = 'excel'
        else:
            App.get_running_app().show_popup("알림", "단어장을 먼저 선택하세요.")

    def go_to_deck_selection(self, instance):
        self.manager.current = 'deck_selection'

class AddCardScreen(Screen):
    def __init__(self, app_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.app_dir = app_dir or get_app_directory()
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        layout = BoxLayout(orientation='vertical')
        self.front_input = TextInput(hint_text='앞면 (단어 또는 의미)', font_name=font_path)
        self.back_input = TextInput(hint_text='뒷면 (단어 또는 의미)', font_name=font_path)
        self.star_button = Button(text='☆', font_name=font_path, on_press=self.toggle_star)
        self.starred = False
        layout.add_widget(self.front_input)
        layout.add_widget(self.back_input)
        layout.add_widget(self.star_button)
        layout.add_widget(Button(text='저장', font_name=font_path, on_press=self.save_card))
        layout.add_widget(Button(text='뒤로', font_name=font_path, on_press=self.go_back))
        self.add_widget(layout)

    def toggle_star(self, instance):
        self.starred = not self.starred
        self.star_button.text = '★' if self.starred else '☆'

    def save_card(self, instance):
        front = self.front_input.text.strip()
        back = self.back_input.text.strip()
        if front and back:
            card = {'front': front, 'back': back, 'starred': self.starred}
            app = App.get_running_app()
            app.cards.append(card)
            app.save_cards()
            self.front_input.text = ''
            self.back_input.text = ''
            self.starred = False
            self.star_button.text = '☆'
        else:
            App.get_running_app().show_popup("오류", "앞면과 뒷면을 모두 입력하세요.")

    def go_back(self, instance):
        self.manager.current = 'main'

class BulkAddScreen(Screen):
    def __init__(self, app_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.app_dir = app_dir or get_app_directory()
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        layout = BoxLayout(orientation='vertical')
        self.input_area = TextInput(hint_text='여러 단어와 의미를 입력하세요 (구분자: -, /, ,)', font_name=font_path)
        layout.add_widget(self.input_area)
        layout.add_widget(Button(text='일괄 추가', font_name=font_path, on_press=self.bulk_add))
        layout.add_widget(Button(text='뒤로', font_name=font_path, on_press=self.go_back))
        self.add_widget(layout)

    def bulk_add(self, instance):
        text = self.input_area.text.strip()
        lines = text.split('\n')
        cards = []
        for line in lines:
            if '-' in line:
                front, back = line.split('-', 1)
                cards.append({'front': front.strip(), 'back': back.strip(), 'starred': False})
        app = App.get_running_app()
        app.cards.extend(cards)
        app.save_cards()
        self.input_area.text = ''
        App.get_running_app().show_popup("성공", f"{len(cards)}개의 카드가 추가되었습니다.")

    def go_back(self, instance):
        self.manager.current = 'main'

class FlashcardScreen(Screen):
    def __init__(self, app_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.app_dir = app_dir or get_app_directory()
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.current_sound = None
        self.current_card_index = 0
        self.showing_front = True
        self.tts_enabled = True
        self.initial_load = True
        self.stop_tts_event = threading.Event()

        self.voice_options = {
            "ko-KR": ["ko-KR-Neural2-A", "ko-KR-Neural2-B", "ko-KR-Neural2-C"],
            "en-US": ["en-US-Neural2-A", "en-US-Standard-B", "en-US-Neural2-C"],
            "fr-FR": ["fr-FR-Standard-A", "fr-FR-Standard-B", "fr-FR-Standard-C"],
            "es-ES": ["es-ES-Standard-A", "es-ES-Standard-B"],
            "de-DE": ["de-DE-Standard-A", "de-DE-Standard-B"]
        }
        self.word_language = "en-US"
        self.meaning_language = "ko-KR"
        self.word_voice = self.voice_options["en-US"][0]
        self.meaning_voice = self.voice_options["ko-KR"][0]

        self.layout = BoxLayout(orientation='vertical')
        self.first_row_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        self.first_row_layout.add_widget(Button(text='수정', font_name=font_path, on_press=self.edit_card))
        self.first_row_layout.add_widget(Button(text='삭제', font_name=font_path, on_press=self.delete_card))
        self.tts_button = Button(text='TTS 재생', font_name=font_path, on_press=self.play_current_card_tts)
        self.first_row_layout.add_widget(self.tts_button)
        self.tts_toggle_button = Button(text='TTS 끄기', font_name=font_path, on_press=self.toggle_tts)
        self.first_row_layout.add_widget(self.tts_toggle_button)
        self.layout.add_widget(self.first_row_layout)

        self.second_row_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        self.second_row_layout.add_widget(Button(text='이전 카드', font_name=font_path, on_press=self.prev_card))
        self.second_row_layout.add_widget(Button(text='카드 뒤집기', font_name=font_path, on_press=self.flip_card))
        self.second_row_layout.add_widget(Button(text='다음 카드', font_name=font_path, on_press=self.next_card))
        self.layout.add_widget(self.second_row_layout)

        self.card_label = Label(
            text='', font_name=font_path, font_size=24, halign='center', valign='middle', size_hint=(1, 0.8),
            text_size=(self.width * 0.95, None)
        )
        self.card_label.bind(size=self.update_text_size)
        self.layout.add_widget(self.card_label)

        self.options_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        self.back_spinner = Spinner(text='뒤로', font_name=font_path, on_press=self.go_back, size_hint_x=0.15)
        self.word_lang_spinner = Spinner(text='단어 언어', font_name=font_path, values=list(self.voice_options.keys()), size_hint_x=0.25)
        self.meaning_lang_spinner = Spinner(text='의미 언어', font_name=font_path, values=list(self.voice_options.keys()), size_hint_x=0.25)
        self.word_voice_spinner = Spinner(text='단어 음성', font_name=font_path, values=self.voice_options["en-US"], size_hint_x=0.25)
        self.meaning_voice_spinner = Spinner(text='의미 음성', font_name=font_path, values=self.voice_options["ko-KR"], size_hint_x=0.25)
        self.word_lang_spinner.bind(text=self.on_word_language_select)
        self.meaning_lang_spinner.bind(text=self.on_meaning_language_select)
        self.word_voice_spinner.bind(text=self.on_word_voice_select)
        self.meaning_voice_spinner.bind(text=self.on_meaning_voice_select)
        self.options_layout.add_widget(self.back_spinner)
        self.options_layout.add_widget(self.word_lang_spinner)
        self.options_layout.add_widget(self.meaning_lang_spinner)
        self.options_layout.add_widget(self.word_voice_spinner)
        self.options_layout.add_widget(self.meaning_voice_spinner)
        self.layout.add_widget(self.options_layout)
        self.add_widget(self.layout)

    def update_text_size(self, instance, value):
        instance.text_size = (instance.width, None)

    def on_word_language_select(self, spinner, text):
        self.word_language = text
        self.word_voice_spinner.values = self.voice_options[text]
        self.word_voice_spinner.text = self.voice_options[text][0]
        self.word_voice = self.voice_options[text][0]

    def on_meaning_language_select(self, spinner, text):
        self.meaning_language = text
        self.meaning_voice_spinner.values = self.voice_options[text]
        self.meaning_voice_spinner.text = self.voice_options[text][0]
        self.meaning_voice = self.voice_options[text][0]

    def on_word_voice_select(self, spinner, text):
        self.word_voice = text

    def on_meaning_voice_select(self, spinner, text):
        self.meaning_voice = text

    def play_current_card_tts(self, instance):
        app = App.get_running_app()
        if self.tts_enabled and app.cards:
            card = app.cards[self.current_card_index]
            text = card['front'] if self.showing_front else card['back']
            language = self.word_language if self.showing_front else self.meaning_language
            voice = self.word_voice if self.showing_front else self.meaning_voice
            self.play_tts(text, language, voice)

    def play_tts(self, text, language, voice):
        app = App.get_running_app()
        if self.current_sound and self.current_sound.state == 'play':
            self.current_sound.stop()
        self.stop_tts_event.clear()

        def tts_thread():
            temp_file_name = None
            try:
                if platform == 'android' and app.tts_engine:
                    locale = Locale('ko', 'KR') if language == 'ko-KR' else Locale('en', 'US')
                    app.tts_engine.setLanguage(locale)
                    app.tts_engine.speak(text, TextToSpeech.QUEUE_FLUSH, None)
                    time.sleep(len(text) * 0.1)
                elif app.tts_client:
                    synthesis_input = texttospeech.SynthesisInput(text=text)
                    voice_params = texttospeech.VoiceSelectionParams(language_code=language, name=voice)
                    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
                    response = app.tts_client.synthesize_speech(input=synthesis_input, voice=voice_params, audio_config=audio_config)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                        temp_file.write(response.audio_content)
                        temp_file_name = temp_file.name
                    self.current_sound = SoundLoader.load(temp_file_name)
                    if self.current_sound:
                        self.current_sound.play()
                        while self.current_sound.state == 'play' and not self.stop_tts_event.is_set():
                            time.sleep(0.1)
                else:
                    tts = gTTS(text=text, lang=language[:2])
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                        tts.save(temp_file.name)
                        temp_file_name = temp_file.name
                    self.current_sound = SoundLoader.load(temp_file_name)
                    if self.current_sound:
                        self.current_sound.play()
                        while self.current_sound.state == 'play' and not self.stop_tts_event.is_set():
                            time.sleep(0.1)
            except Exception as e:
                print(f"TTS 재생 오류: {e}")
            finally:
                if self.current_sound:
                    self.current_sound.stop()
                    self.current_sound = None
                if temp_file_name and os.path.exists(temp_file_name):
                    try:
                        os.unlink(temp_file_name)
                    except Exception as e:
                        print(f"파일 삭제 오류: {e}")

        threading.Thread(target=tts_thread).start()

    def on_enter(self):
        app = App.get_running_app()
        self.current_card_index = 0
        self.initial_load = True
        self.show_card()

    def show_card(self):
        app = App.get_running_app()
        if app.cards:
            if 0 <= self.current_card_index < len(app.cards):
                card = app.cards[self.current_card_index]
                self.card_label.text = card['front'] if self.showing_front else card['back']
                if not self.initial_load and self.tts_enabled:
                    self.play_current_card_tts(None)
            else:
                self.card_label.text = "카드 인덱스가 범위를 벗어났습니다."
        else:
            self.card_label.text = "카드가 없습니다."
        self.initial_load = False

    def prev_card(self, instance):
        app = App.get_running_app()
        if app.cards:
            self.current_card_index = (self.current_card_index - 1) % len(app.cards)
            self.showing_front = True
            self.show_card()

    def next_card(self, instance):
        app = App.get_running_app()
        if app.cards:
            self.current_card_index = (self.current_card_index + 1) % len(app.cards)
            self.showing_front = True
            self.show_card()

    def flip_card(self, instance):
        self.showing_front = not self.showing_front
        self.show_card()

    def toggle_tts(self, instance):
        self.tts_enabled = not self.tts_enabled
        self.tts_toggle_button.text = 'TTS 켜기' if not self.tts_enabled else 'TTS 끄기'

    def go_back(self, instance):
        self.manager.current = 'main'

    def edit_card(self, instance):
        app = App.get_running_app()
        if not app.cards:
            return
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.layout.clear_widgets()
        edit_layout = BoxLayout(orientation='vertical')
        front_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        front_layout.add_widget(Label(text='앞면:', font_name=font_path, size_hint_x=0.2))
        self.front_input = TextInput(text=app.cards[self.current_card_index]['front'], font_name=font_path, multiline=False)
        front_layout.add_widget(self.front_input)
        edit_layout.add_widget(front_layout)
        back_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        back_layout.add_widget(Label(text='뒷면:', font_name=font_path, size_hint_x=0.2))
        self.back_input = TextInput(text=app.cards[self.current_card_index]['back'], font_name=font_path, multiline=False)
        back_layout.add_widget(self.back_input)
        edit_layout.add_widget(back_layout)
        button_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        button_layout.add_widget(Button(text='저장', font_name=font_path, on_press=self.save_edited_card))
        button_layout.add_widget(Button(text='취소', font_name=font_path, on_press=self.cancel_edit))
        edit_layout.add_widget(button_layout)
        self.layout.add_widget(edit_layout)

    def save_edited_card(self, instance):
        app = App.get_running_app()
        front = self.front_input.text.strip()
        back = self.back_input.text.strip()
        if front and back:
            app.cards[self.current_card_index]['front'] = front
            app.cards[self.current_card_index]['back'] = back
            app.save_cards()
            self.layout.clear_widgets()
            self.layout.add_widget(self.first_row_layout)
            self.layout.add_widget(self.second_row_layout)
            self.layout.add_widget(self.card_label)
            self.layout.add_widget(self.options_layout)
            self.show_card()

    def cancel_edit(self, instance):
        self.layout.clear_widgets()
        self.layout.add_widget(self.first_row_layout)
        self.layout.add_widget(self.second_row_layout)
        self.layout.add_widget(self.card_label)
        self.layout.add_widget(self.options_layout)
        self.show_card()

    def delete_card(self, instance):
        app = App.get_running_app()
        if app.cards:
            app.cards.pop(self.current_card_index)
            app.save_cards()
            if self.current_card_index >= len(app.cards):
                self.current_card_index = len(app.cards) - 1 if app.cards else 0
            self.show_card()

class ExcelScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.font_size = 22
        self.app_dir = get_app_directory()
        self.layout = BoxLayout(orientation='vertical')
        self.grid = GridLayout(cols=3, spacing=10, size_hint_y=None)
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll = ScrollView(size_hint=(1, 1))
        self.scroll.add_widget(self.grid)
        self.layout.add_widget(self.scroll)
        self.current_sound = None
        self.stop_tts_event = threading.Event()
        self.tts_enabled = True
        self.words_hidden = False
        self.meanings_hidden = False

        self.voice_options = {
            "ko-KR": ["ko-KR-Neural2-A", "ko-KR-Neural2-B", "ko-KR-Neural2-C"],
            "en-US": ["en-US-Neural2-A", "en-US-Standard-B", "en-US-Neural2-C"],
            "fr-FR": ["fr-FR-Standard-A", "fr-FR-Standard-B", "fr-FR-Standard-C"],
            "es-ES": ["es-ES-Standard-A", "es-ES-Standard-B"],
            "de-DE": ["de-DE-Standard-A", "de-DE-Standard-B"]
        }
        self.word_language = "en-US"
        self.meaning_language = "ko-KR"
        self.word_voice = self.voice_options["en-US"][0]
        self.meaning_voice = self.voice_options["ko-KR"][0]

        self.menu_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        self.menu_layout.add_widget(Button(text='뒤로', font_name=font_path, on_press=self.go_back, size_hint_x=0.1, font_size=15))
        self.tts_toggle_button = Button(text='TTS 끄기', font_name=font_path, on_press=self.toggle_tts, size_hint_x=0.18, font_size=15)
        self.menu_layout.add_widget(self.tts_toggle_button)

        button_size_hint = 0.18
        self.word_lang_spinner = Spinner(text='단어 언어', font_name=font_path, values=list(self.voice_options.keys()), size_hint_x=button_size_hint, height=50, font_size=16)
        self.word_lang_spinner.bind(text=self.on_word_language_select)
        self.menu_layout.add_widget(self.word_lang_spinner)
        self.meaning_lang_spinner = Spinner(text='의미 언어', font_name=font_path, values=list(self.voice_options.keys()), size_hint_x=button_size_hint, height=50, font_size=16)
        self.meaning_lang_spinner.bind(text=self.on_meaning_language_select)
        self.menu_layout.add_widget(self.meaning_lang_spinner)
        self.word_voice_spinner = Spinner(text='단어 음성', font_name=font_path, values=self.voice_options[self.word_language], size_hint_x=button_size_hint, height=50, font_size=16)
        self.word_voice_spinner.bind(text=self.on_word_voice_select)
        self.menu_layout.add_widget(self.word_voice_spinner)
        self.meaning_voice_spinner = Spinner(text='의미 음성', font_name=font_path, values=self.voice_options[self.meaning_language], size_hint_x=button_size_hint, height=50, font_size=16)
        self.meaning_voice_spinner.bind(text=self.on_meaning_voice_select)
        self.menu_layout.add_widget(self.meaning_voice_spinner)
        self.layout.add_widget(self.menu_layout)
        self.add_widget(self.layout)
        self.context_menu = None

    def on_enter(self):
        self.load_cards()

    def go_back(self, instance):
        self.manager.current = 'main'

    def load_cards(self):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.grid.clear_widgets()
        self.grid.add_widget(Label(text='번호', font_name=font_path, size_hint_y=None, height=40, size_hint_x=0.1, font_size=self.font_size))
        word_header = Label(text='단어', font_name=font_path, size_hint_y=None, height=40, size_hint_x=0.45, font_size=self.font_size)
        word_header.bind(on_touch_down=self.toggle_words_visibility)
        self.grid.add_widget(word_header)
        meaning_header = Label(text='의미', font_name=font_path, size_hint_y=None, height=40, size_hint_x=0.45, font_size=self.font_size)
        meaning_header.bind(on_touch_down=self.toggle_meanings_visibility)
        self.grid.add_widget(meaning_header)

        app = App.get_running_app()
        for index, card in enumerate(app.cards):
            number_label = Label(text=str(index + 1), font_name=font_path, size_hint_y=None, height=40, size_hint_x=0.1, font_size=self.font_size)
            number_label.card_index = index
            number_label.card_side = 'number'
            number_label.bind(on_touch_down=self.on_cell_touch)
            front_label = Label(text=card['front'], font_name=font_path, size_hint_y=None, size_hint_x=0.45, font_size=self.font_size)
            front_label.bind(size=self.update_label_text_size)
            front_label.bind(texture_size=self.update_label_height)
            front_label.card_index = index
            front_label.card_side = 'front'
            front_label.bind(on_touch_down=self.on_cell_touch)
            back_label = Label(text=card['back'], font_name=font_path, size_hint_y=None, size_hint_x=0.45, font_size=self.font_size)
            back_label.bind(size=self.update_label_text_size)
            back_label.bind(texture_size=self.update_label_height)
            back_label.card_index = index
            back_label.card_side = 'back'
            back_label.bind(on_touch_down=self.on_cell_touch)
            self.grid.add_widget(number_label)
            self.grid.add_widget(front_label)
            self.grid.add_widget(back_label)

    def on_cell_touch(self, instance, touch):
        if instance.collide_point(*touch.pos):
            app = App.get_running_app()
            card = app.cards[instance.card_index]
            if instance.card_side in ['front', 'back']:
                instance.text = '-' if instance.text != '-' else card[instance.card_side]
            if self.tts_enabled:
                if self.current_sound and self.current_sound.state == 'play':
                    self.current_sound.stop()
                else:
                    if instance.card_side == 'number':
                        self.synthesize_speech(word=card['front'], word_lang=self.word_language, word_voice=self.word_voice,
                                              meaning=card['back'], meaning_lang=self.meaning_language, meaning_voice=self.meaning_voice)
                    elif instance.card_side == 'front':
                        self.synthesize_speech(word=card['front'], word_lang=self.word_language, word_voice=self.word_voice)
                    elif instance.card_side == 'back':
                        self.synthesize_speech(meaning=card['back'], meaning_lang=self.meaning_language, meaning_voice=self.meaning_voice)
            if touch.is_double_tap:
                self.show_context_menu(instance.card_index)

    def update_label_text_size(self, instance, size):
        instance.text_size = (size[0], None)

    def update_label_height(self, instance, size):
        instance.height = size[1]

    def toggle_words_visibility(self, instance, touch):
        if instance.collide_point(*touch.pos):
            self.words_hidden = not self.words_hidden
            app = App.get_running_app()
            for i in range(1, len(self.grid.children) - 2, 3):
                child = self.grid.children[i]
                if isinstance(child, Label) and hasattr(child, 'card_index'):
                    child.text = '-' if self.words_hidden else app.cards[child.card_index]['front']

    def toggle_meanings_visibility(self, instance, touch):
        if instance.collide_point(*touch.pos):
            self.meanings_hidden = not self.meanings_hidden
            app = App.get_running_app()
            for i in range(0, len(self.grid.children) - 2, 3):
                child = self.grid.children[i]
                if isinstance(child, Label) and hasattr(child, 'card_index'):
                    child.text = '-' if self.meanings_hidden else app.cards[child.card_index]['back']

    def synthesize_speech(self, word=None, word_lang=None, word_voice=None, meaning=None, meaning_lang=None, meaning_voice=None):
        app = App.get_running_app()
        if self.current_sound and self.current_sound.state == 'play':
            self.current_sound.stop()
        self.stop_tts_event.clear()

        def play_tts_sequence():
            try:
                if platform == 'android' and app.tts_engine:
                    if word and meaning:
                        locale = Locale('ko', 'KR') if word_lang == 'ko-KR' else Locale('en', 'US')
                        app.tts_engine.setLanguage(locale)
                        app.tts_engine.speak(word, TextToSpeech.QUEUE_FLUSH, None)
                        time.sleep(1.5)
                        locale = Locale('ko', 'KR') if meaning_lang == 'ko-KR' else Locale('en', 'US')
                        app.tts_engine.setLanguage(locale)
                        app.tts_engine.speak(meaning, TextToSpeech.QUEUE_FLUSH, None)
                    elif word:
                        locale = Locale('ko', 'KR') if word_lang == 'ko-KR' else Locale('en', 'US')
                        app.tts_engine.setLanguage(locale)
                        app.tts_engine.speak(word, TextToSpeech.QUEUE_FLUSH, None)
                    elif meaning:
                        locale = Locale('ko', 'KR') if meaning_lang == 'ko-KR' else Locale('en', 'US')
                        app.tts_engine.setLanguage(locale)
                        app.tts_engine.speak(meaning, TextToSpeech.QUEUE_FLUSH, None)
                elif app.tts_client:
                    if word and meaning:
                        self.play_tts(word, word_lang, word_voice)
                        time.sleep(1.5)
                        self.play_tts(meaning, meaning_lang, meaning_voice)
                    elif word:
                        self.play_tts(word, word_lang, word_voice)
                    elif meaning:
                        self.play_tts(meaning, meaning_lang, meaning_voice)
                else:
                    if word and meaning:
                        tts = gTTS(text=word, lang=word_lang[:2])
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                            tts.save(temp_file.name)
                            self.current_sound = SoundLoader.load(temp_file.name)
                            self.current_sound.play()
                            while self.current_sound.state == 'play' and not self.stop_tts_event.is_set():
                                time.sleep(0.1)
                            os.unlink(temp_file.name)
                        tts = gTTS(text=meaning, lang=meaning_lang[:2])
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                            tts.save(temp_file.name)
                            self.current_sound = SoundLoader.load(temp_file.name)
                            self.current_sound.play()
                            while self.current_sound.state == 'play' and not self.stop_tts_event.is_set():
                                time.sleep(0.1)
                            os.unlink(temp_file.name)
                    elif word:
                        tts = gTTS(text=word, lang=word_lang[:2])
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                            tts.save(temp_file.name)
                            self.current_sound = SoundLoader.load(temp_file.name)
                            self.current_sound.play()
                            while self.current_sound.state == 'play' and not self.stop_tts_event.is_set():
                                time.sleep(0.1)
                            os.unlink(temp_file.name)
                    elif meaning:
                        tts = gTTS(text=meaning, lang=meaning_lang[:2])
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                            tts.save(temp_file.name)
                            self.current_sound = SoundLoader.load(temp_file.name)
                            self.current_sound.play()
                            while self.current_sound.state == 'play' and not self.stop_tts_event.is_set():
                                time.sleep(0.1)
                            os.unlink(temp_file.name)
            except Exception as e:
                print(f"TTS 재생 중 오류 발생: {e}")
            finally:
                self.current_sound = None

        threading.Thread(target=play_tts_sequence).start()

    def play_tts(self, text, language, voice):
        app = App.get_running_app()
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice_params = texttospeech.VoiceSelectionParams(language_code=language, name=voice)
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            response = app.tts_client.synthesize_speech(input=synthesis_input, voice=voice_params, audio_config=audio_config)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                temp_file.write(response.audio_content)
                temp_file_name = temp_file.name
            self.current_sound = SoundLoader.load(temp_file_name)
            if self.current_sound:
                self.current_sound.play()
                while self.current_sound.state == 'play' and not self.stop_tts_event.is_set():
                    time.sleep(0.1)
        except Exception as e:
            print(f"TTS 재생 오류: {e}")
        finally:
            if self.current_sound:
                self.current_sound.stop()
                self.current_sound = None
            if 'temp_file_name' in locals() and os.path.exists(temp_file_name):
                try:
                    os.unlink(temp_file_name)
                except Exception as e:
                    print(f"파일 삭제 오류: {e}")

    def show_context_menu(self, index):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        if self.context_menu:
            self.context_menu.dismiss()
        content = BoxLayout(orientation='vertical', size_hint_y=None, height=100)
        content.add_widget(Button(text='편집', font_name=font_path, on_press=lambda x: self.edit_card(index)))
        content.add_widget(Button(text='삭제', font_name=font_path, on_press=lambda x: self.delete_card(index)))
        self.context_menu = Popup(title='옵션', content=content, size_hint=(0.3, 0.3))
        self.context_menu.open()

    def edit_card(self, index):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        app = App.get_running_app()
        card = app.cards[index]
        content = BoxLayout(orientation='vertical')
        front_input = TextInput(text=card['front'], font_name=font_path, multiline=False)
        back_input = TextInput(text=card['back'], font_name=font_path, multiline=False)
        content.add_widget(front_input)
        content.add_widget(back_input)
        content.add_widget(Button(text='저장', font_name=font_path, on_press=lambda x: self.save_edited_card(index, front_input.text, back_input.text)))
        popup = Popup(title='카드 편집', content=content, size_hint=(0.7, 0.5))
        popup.open()

    def save_edited_card(self, index, front, back):
        app = App.get_running_app()
        app.cards[index]['front'] = front.strip()
        app.cards[index]['back'] = back.strip()
        app.save_cards()
        self.load_cards()

    def delete_card(self, index):
        app = App.get_running_app()
        app.cards.pop(index)
        app.save_cards()
        self.load_cards()

    def on_word_language_select(self, spinner, text):
        self.word_language = text
        self.word_voice_spinner.values = self.voice_options[text]
        self.word_voice_spinner.text = self.voice_options[text][0]
        self.word_voice = self.voice_options[text][0]

    def on_meaning_language_select(self, spinner, text):
        self.meaning_language = text
        self.meaning_voice_spinner.values = self.voice_options[text]
        self.meaning_voice_spinner.text = self.voice_options[text][0]
        self.meaning_voice = self.voice_options[text][0]

    def on_word_voice_select(self, spinner, text):
        self.word_voice = text

    def on_meaning_voice_select(self, spinner, text):
        self.meaning_voice = text

    def toggle_tts(self, instance):
        self.tts_enabled = not self.tts_enabled
        self.tts_toggle_button.text = 'TTS 켜기' if not self.tts_enabled else 'TTS 끄기'

class DeckSelectionScreen(Screen):
    def __init__(self, app_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.app_dir = app_dir or get_app_directory()
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.layout = BoxLayout(orientation='vertical')
        self.current_title = None

        self.top_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        self.new_title_input = TextInput(hint_text='새 단어장 제목', font_name=font_path, multiline=False, size_hint_x=0.5)
        self.add_button = Button(text='추가', font_name=font_path, size_hint_x=0.15, on_press=self.add_new_deck_title)
        self.import_button = Button(text='파일 불러오기', font_name=font_path, size_hint_x=0.25, on_press=self.open_file_chooser)
        self.back_button = Button(text='뒤로', font_name=font_path, size_hint_x=0.15, on_press=self.go_back)
        self.top_layout.add_widget(self.new_title_input)
        self.top_layout.add_widget(self.add_button)
        self.top_layout.add_widget(self.import_button)
        self.top_layout.add_widget(self.back_button)
        
        self.layout.add_widget(self.top_layout)
        self.scroll_view = ScrollView(size_hint=(1, None), size=(Window.width, Window.height - 50))
        self.deck_list = BoxLayout(orientation='vertical', spacing=1, size_hint_y=None)
        self.deck_list.bind(minimum_height=self.deck_list.setter('height'))
        self.scroll_view.add_widget(self.deck_list)
        self.layout.add_widget(self.scroll_view)
        self.add_widget(self.layout)

    def on_enter(self):
        self.load_decks()

    def load_decks(self, *args):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.deck_list.clear_widgets()
        deck_dir = os.path.join(self.app_dir, 'decks')
        if not os.path.exists(deck_dir):
            os.makedirs(deck_dir, exist_ok=True)
            print(f"데크 디렉토리 생성: {deck_dir}")
        
        deck_titles = [d for d in os.listdir(deck_dir) if os.path.isdir(os.path.join(deck_dir, d))]
        print(f"불러온 단어장 목록: {deck_titles}")
        
        if not deck_titles:
            self.deck_list.add_widget(Label(text="단어장이 없습니다.", font_name=font_path, size_hint_y=None, height=50))
        else:
            for title_name in deck_titles:
                title_button = Button(text=title_name, font_name=font_path, size_hint_y=None, height=50)
                title_button.bind(on_press=lambda x, tn=title_name: self.show_deck_options(tn))
                self.deck_list.add_widget(title_button)
                separator = Widget(size_hint_y=None, height=1)
                with separator.canvas:
                    Color(0.5, 0.5, 0.5)
                    Rectangle(pos=separator.pos, size=separator.size)
                self.deck_list.add_widget(separator)

    def add_new_deck_title(self, instance):
        title_name = self.new_title_input.text.strip()
        if not title_name:
            App.get_running_app().show_popup("오류", "단어장 제목을 입력하세요.")
            print("입력값 없음: 단어장 제목 미입력")
            return
        title_dir = os.path.join(self.app_dir, 'decks', title_name)
        try:
            if not os.path.exists(title_dir):
                os.makedirs(title_dir, exist_ok=True)
                print(f"단어장 디렉토리 생성 성공: {title_dir}")
                self.new_title_input.text = ''
                self.load_decks()
            else:
                App.get_running_app().show_popup("오류", "이미 존재하는 단어장 제목입니다.")
                print(f"중복 단어장: {title_dir}")
        except Exception as e:
            App.get_running_app().show_popup("오류", f"단어장 추가 실패: {str(e)}")
            print(f"단어장 생성 오류: {e}")

    def open_file_chooser(self, instance):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        content = BoxLayout(orientation='vertical')
        self.file_chooser = FileChooserListView(path=os.getcwd(), filters=['*.json', '*.txt'])
        content.add_widget(self.file_chooser)
        content.add_widget(Button(text='불러오기', font_name=font_path, on_press=self.import_deck))
        content.add_widget(Button(text='취소', font_name=font_path, on_press=lambda x: self.file_popup.dismiss()))
        self.file_popup = Popup(title='단어장 파일 선택', content=content, size_hint=(0.9, 0.9))
        self.file_popup.open()

    def import_deck(self, instance):
        selected_file = self.file_chooser.selection and self.file_chooser.selection[0]
        if not selected_file:
            App.get_running_app().show_popup("오류", "파일을 선택하세요.")
            return
        try:
            title_name = os.path.splitext(os.path.basename(selected_file))[0]
            title_dir = os.path.join(self.app_dir, 'decks', title_name)
            if not os.path.exists(title_dir):
                os.makedirs(title_dir, exist_ok=True)
            if selected_file.endswith('.json'):
                with open(selected_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            elif selected_file.endswith('.txt'):
                data = []
                with open(selected_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        front, back = line.strip().split('-', 1)
                        data.append({'front': front.strip(), 'back': back.strip(), 'starred': False})
            else:
                App.get_running_app().show_popup("오류", "지원하지 않는 파일 형식입니다.")
                return
            flashcards_path = os.path.join(title_dir, 'flashcards.json')
            with open(flashcards_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"단어장 불러오기 성공: {title_name}")
            self.file_popup.dismiss()
            self.load_decks()
        except Exception as e:
            App.get_running_app().show_popup("오류", f"파일 불러오기 실패: {str(e)}")
            print(f"파일 불러오기 오류: {e}")

    def go_back(self, instance):
        if self.current_title:
            self.go_back_to_titles(instance)
        else:
            self.manager.current = 'main'

    def go_back_to_titles(self, instance):
        self.current_title = None
        self.layout.clear_widgets()
        self.layout.add_widget(self.top_layout)
        self.layout.add_widget(self.scroll_view)
        self.load_decks()

    def show_deck_options(self, title_name):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.current_title = title_name
        self.layout.clear_widgets()
        
        top_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
        top_layout.add_widget(Button(text=f'{title_name}에 새 단어장 추가', font_name=font_path, size_hint_x=0.4, on_press=lambda x: self.add_new_deck(title_name)))
        top_layout.add_widget(Button(text='파일 불러오기', font_name=font_path, size_hint_x=0.2, on_press=lambda x: self.open_subdeck_file_chooser(title_name)))
        top_layout.add_widget(Button(text='단어장 제목 목록으로', font_name=font_path, size_hint_x=0.2, on_press=self.go_back_to_titles))
        top_layout.add_widget(Button(text='뒤로', font_name=font_path, size_hint_x=0.2, on_press=self.go_back))
        self.layout.add_widget(top_layout)
        
        scroll_view = ScrollView(size_hint=(1, None), size=(Window.width, Window.height - 50))
        deck_list = BoxLayout(orientation='vertical', spacing=1, size_hint_y=None)
        deck_list.bind(minimum_height=deck_list.setter('height'))
        
        deck_dir = os.path.join(self.app_dir, 'decks', title_name)
        for deck_name in os.listdir(deck_dir):
            if os.path.isdir(os.path.join(deck_dir, deck_name)):
                deck_layout = BoxLayout(orientation='horizontal', size_hint_y=None, height=50)
                deck_layout.add_widget(Button(text=deck_name, font_name=font_path, on_press=lambda x, dn=deck_name: self.select_deck(dn)))
                deck_layout.add_widget(Button(text='설정', font_name=font_path, on_press=lambda x, dn=deck_name: self.configure_deck(deck_name=dn, title_name=title_name)))
                deck_layout.add_widget(Button(text='삭제', font_name=font_path, on_press=lambda x, dn=deck_name: self.delete_deck(title_name, dn)))
                deck_list.add_widget(deck_layout)
        
        scroll_view.add_widget(deck_list)
        self.layout.add_widget(scroll_view)

    def open_subdeck_file_chooser(self, title_name):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        content = BoxLayout(orientation='vertical')
        self.subdeck_file_chooser = FileChooserListView(path=os.getcwd(), filters=['*.json', '*.txt'])
        content.add_widget(self.subdeck_file_chooser)
        content.add_widget(Button(text='불러오기', font_name=font_path, on_press=lambda x: self.import_deck_to_subdeck(title_name)))
        content.add_widget(Button(text='취소', font_name=font_path, on_press=lambda x: self.subdeck_file_popup.dismiss()))
        self.subdeck_file_popup = Popup(title=f'{title_name}에 파일 불러오기', content=content, size_hint=(0.9, 0.9))
        self.subdeck_file_popup.open()

    def import_deck_to_subdeck(self, title_name):
        selected_file = self.subdeck_file_chooser.selection and self.subdeck_file_chooser.selection[0]
        if not selected_file:
            App.get_running_app().show_popup("오류", "파일을 선택하세요.")
            return
        try:
            deck_name = os.path.splitext(os.path.basename(selected_file))[0]
            deck_dir = os.path.join(self.app_dir, 'decks', title_name, deck_name)
            if not os.path.exists(deck_dir):
                os.makedirs(deck_dir, exist_ok=True)
            if selected_file.endswith('.json'):
                with open(selected_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            elif selected_file.endswith('.txt'):
                data = []
                with open(selected_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        front, back = line.strip().split('-', 1)
                        data.append({'front': front.strip(), 'back': back.strip(), 'starred': False})
            else:
                App.get_running_app().show_popup("오류", "지원하지 않는 파일 형식입니다.")
                return
            flashcards_path = os.path.join(deck_dir, 'flashcards.json')
            with open(flashcards_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"하위 단어장 불러오기 성공: {deck_name}")
            self.subdeck_file_popup.dismiss()
            self.show_deck_options(title_name)
        except Exception as e:
            App.get_running_app().show_popup("오류", f"파일 불러오기 실패: {str(e)}")
            print(f"파일 불러오기 오류: {e}")

    def add_new_deck(self, title_name):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.layout.clear_widgets()
        deck_layout = BoxLayout(orientation='vertical')
        self.deck_name_input = TextInput(hint_text='단어장 이름 입력', font_name=font_path, multiline=False)
        self.front_lang_spinner = Spinner(text='앞면 언어 선택', font_name=font_path, values=('en', 'fr', 'es', 'de', 'ko'))
        self.back_lang_spinner = Spinner(text='뒷면 언어 선택', font_name=font_path, values=('en', 'fr', 'es', 'de', 'ko'))
        save_button = Button(text='저장', font_name=font_path, on_press=lambda x: self.save_new_deck(title_name))
        cancel_button = Button(text='취소', font_name=font_path, on_press=lambda x: self.show_deck_options(title_name))
        deck_layout.add_widget(self.deck_name_input)
        deck_layout.add_widget(self.front_lang_spinner)
        deck_layout.add_widget(self.back_lang_spinner)
        deck_layout.add_widget(save_button)
        deck_layout.add_widget(cancel_button)
        self.layout.add_widget(deck_layout)

    def save_new_deck(self, title_name):
        deck_name = self.deck_name_input.text.strip()
        front_lang = self.front_lang_spinner.text
        back_lang = self.back_lang_spinner.text
        if not deck_name:
            App.get_running_app().show_popup("오류", "단어장 이름을 입력하세요.")
            return
        deck_dir = os.path.join(self.app_dir, 'decks', title_name, deck_name)
        try:
            if not os.path.exists(deck_dir):
                os.makedirs(deck_dir, exist_ok=True)
                settings = {'front_lang': front_lang, 'back_lang': back_lang}
                settings_path = os.path.join(deck_dir, 'settings.json')
                with open(settings_path, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, ensure_ascii=False, indent=2)
                print(f"새 단어장 저장: {deck_dir}")
                self.show_deck_options(title_name)
            else:
                App.get_running_app().show_popup("오류", "이미 존재하는 단어장 이름입니다.")
        except Exception as e:
            App.get_running_app().show_popup("오류", f"단어장 저장 실패: {str(e)}")
            print(f"단어장 저장 오류: {e}")

    def configure_deck(self, title_name, deck_name):
        font_path = os.path.join(os.getcwd(), 'fonts', 'NanumGothic-Regular.ttf')
        self.title_name = title_name
        self.deck_name = deck_name
        self.layout.clear_widgets()
        config_layout = BoxLayout(orientation='vertical')
        self.front_lang_spinner = Spinner(text='앞면 언어 선택', font_name=font_path, values=('en', 'fr', 'es', 'de', 'ko'))
        self.back_lang_spinner = Spinner(text='뒷면 언어 선택', font_name=font_path, values=('en', 'fr', 'es', 'de', 'ko'))
        save_button = Button(text='저장', font_name=font_path, on_press=self.save_deck_settings)
        config_layout.add_widget(self.front_lang_spinner)
        config_layout.add_widget(self.back_lang_spinner)
        config_layout.add_widget(save_button)
        config_layout.add_widget(Button(text='취소', font_name=font_path, on_press=lambda x: self.show_deck_options(title_name)))
        self.layout.add_widget(config_layout)

    def save_deck_settings(self, instance):
        front_lang = self.front_lang_spinner.text
        back_lang = self.back_lang_spinner.text
        deck_dir = os.path.join(self.app_dir, 'decks', self.title_name, self.deck_name)
        settings = {'front_lang': front_lang, 'back_lang': back_lang}
        settings_path = os.path.join(deck_dir, 'settings.json')
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        self.show_deck_options(self.title_name)

    def select_deck(self, deck_name):
        if self.current_title:
            self.manager.current = 'main'
            app = App.get_running_app()
            app.current_deck = os.path.join(self.current_title, deck_name)
            app.load_cards()

    def delete_deck(self, title_name, deck_name):
        deck_dir = os.path.join(self.app_dir, 'decks', title_name, deck_name)
        if os.path.exists(deck_dir):
            import shutil
            shutil.rmtree(deck_dir)
            self.show_deck_options(title_name)

if __name__ == '__main__':
    try:
        FlashcardApp().run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_dir = get_app_directory()
        log_file = os.path.join(log_dir, 'error_log.txt')
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"앱 오류: {str(e)}\n")
            traceback.print_exc(file=f)