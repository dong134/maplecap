from tkinter import ttk
import os
import json
import threading
import cv2
import numpy as np
from PIL import Image, ImageTk, ImageGrab
import pyautogui
from pynput import keyboard
import pyperclip
import pygetwindow as gw
from tkinter import messagebox

import ctypes, requests, tkinter as tk
from datetime import datetime
import sys
import time

PASS = False
# 설정 파일 경로
CONFIG_FILE = "screen_app_config.json"
# 데이터 폴더 경로
DATA_FOLDER = "DATA"

# "MapleStory Worlds-Mapleland" 이름을 가진 모든 창 찾기
maple_windows = gw.getWindowsWithTitle('MapleStory Worlds-Mapleland')

# 찾은 창의 개수 출력
print(f"찾은 MapleStory Worlds-Mapleland 창 개수: {len(maple_windows)}")

# 각 메이플스토리 창마다 1000x600 크기로 조정하고 위치를 (0,0)으로 이동
for window in maple_windows:
    try:
        window.resizeTo(1000, 600)
        window.moveTo(0, 0)
        print(f"크기 조정 및 이동 완료: {window.title}")
    except Exception as e:
        print(f"창 크기 조정/이동 실패: {window.title} - 오류: {e}")


class ScreenshotRegionSelector:
    def __init__(self, on_selection_complete, selection_type="capture"):
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.root, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.start_x = None
        self.start_y = None
        self.current_rect = None
        self.selection_complete = False
        self.on_selection_complete = on_selection_complete
        self.selection_type = selection_type  # 선택 타입 (capture 또는 detect)

        # 가이드 텍스트 (선택 타입에 따라 다른 메시지)
        guide_text = "캡처할 영역을 드래그하여 선택하세요. ESC 키를 누르면 취소됩니다."
        if selection_type == "detect":
            guide_text = "감지할 영역을 드래그하여 선택하세요. ESC 키를 누르면 취소됩니다."

        self.canvas.create_text(
            self.root.winfo_screenwidth() // 2,
            30,
            text=guide_text,
            fill="black",
            font=("Arial", 14, "bold")
        )

        # 이벤트 바인딩
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Escape>", self.on_escape)

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y

        if self.current_rect:
            self.canvas.delete(self.current_rect)

        self.current_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline='red', width=2
        )

    def on_mouse_drag(self, event):
        if self.current_rect:
            self.canvas.coords(self.current_rect, self.start_x, self.start_y, event.x, event.y)

            # 크기 표시
            width = abs(event.x - self.start_x)
            height = abs(event.y - self.start_y)
            self.canvas.delete("size_text")
            self.canvas.create_text(
                (self.start_x + event.x) // 2,
                (self.start_y + event.y) // 2,
                text=f"{width} x {height}",
                fill="black",
                font=("Arial", 10),
                tags="size_text"
            )

    def on_button_release(self, event):
        if self.start_x is not None and self.start_y is not None:
            x1 = min(self.start_x, event.x)
            y1 = min(self.start_y, event.y)
            x2 = max(self.start_x, event.x)
            y2 = max(self.start_y, event.y)

            # 선택 영역이 너무 작으면 무시
            if x2 - x1 > 10 and y2 - y1 > 10:
                self.selection_complete = True
                self.root.destroy()
                if self.on_selection_complete:
                    # 캡처와 감지 기능 모두를 위한 일관된 형식으로 영역 반환
                    # x1, y1, x2, y2 (절대 좌표) 형식 사용
                    self.on_selection_complete((x1, y1, x2, y2), self.selection_type)
            else:
                # 영역이 너무 작으면 다시 선택하도록 함
                self.canvas.delete(self.current_rect)
                self.current_rect = None

    def on_escape(self, event):
        self.root.destroy()
        if self.on_selection_complete:
            self.on_selection_complete(None, self.selection_type)

    def start_selection(self):
        self.root.mainloop()


class CombinedApp:
    def __init__(self, root):
        self.root = root
        self.root.title("화면 캡처 및 이미지 감지")
        self.root.geometry("500x700")
        self.root.resizable(True, True)

        # 선택된 영역 정보 (캡처와 감지 범위 분리)
        self.capture_region = None  # 캡처 영역 (x1, y1, x2, y2) 형식
        self.detect_region = None  # 감지 영역 (x1, y1, x2, y2) 형식

        # 저장 경로 설정
        self.save_path = os.path.join(os.path.expanduser("~"), "Desktop", "Screenshots")
        if not os.path.exists(self.save_path):
            os.makedirs(self.save_path)

        # 데이터 폴더 확인
        if not os.path.exists(DATA_FOLDER):
            os.makedirs(DATA_FOLDER)

        # 참조 이미지 로드
        self.reference_images = {}
        self.load_reference_images()

        # 설정 변수들
        self.always_on_top = True
        self.auto_copy_filename = True
        self.detection_threshold = 0.8
        self.detection_active = False  # 이미지 감지 활성화 상태

        # 캡처 모드
        self.capture_mode = False

        # 마지막 감지된 이미지 이름
        self.detected_name = ""
        self.last_copied_name = ""

        # 전역 키보드 리스너
        self.listener = None

        # 클립보드 타이머
        self.clipboard_timer = None

        # 감지 스레드
        self.detection_thread = None
        self.running = True

        # 저장된 설정 불러오기
        self.load_settings()

        # GUI 설정
        self.setup_gui()

        # 전역 단축키 설정
        self.setup_global_hotkeys()

        # 종료 시 정리 작업
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_gui(self):
        # 항상 위에 표시 설정 적용
        if self.always_on_top:
            self.root.attributes("-topmost", True)

        # 탭 컨트롤 생성
        self.tab_control = ttk.Notebook(self.root)

        # 감지 탭
        self.detector_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.detector_tab, text="이미지 감지")

        # 캡처 탭
        self.capture_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.capture_tab, text="화면 캡처")

        self.tab_control.pack(expand=1, fill="both")

        # 공통 영역 정보 프레임
        region_frame = tk.LabelFrame(self.root, text="영역 설정", padx=10, pady=10)
        region_frame.pack(fill=tk.X, padx=10, pady=5)

        # 영역 선택 정보 및 버튼
        region_info_frame = tk.Frame(region_frame)
        region_info_frame.pack(fill=tk.X, pady=5)

        self.detect_region_info_label = tk.Label(
            region_info_frame,
            text="감지 범위: 없음",
            font=("Arial", 9)
        )
        self.detect_region_info_label.pack(side=tk.TOP, padx=5)

        self.capture_region_info_label = tk.Label(
            region_info_frame,
            text="캡처 범위: 없음",
            font=("Arial", 9)
        )
        self.capture_region_info_label.pack(side=tk.TOP, padx=5)

        # 영역 선택 버튼 (분리)
        self.select_capture_region_btn = tk.Button(
            region_info_frame,
            text="캡처범위설정",
            command=self.start_capture_region_selection
        )

        # 감지 영역 선택 버튼
        self.select_detect_region_btn = tk.Button(
            region_info_frame,
            text="감지범위설정",
            command=self.start_detect_region_selection
        )

        # 설정 저장 버튼
        self.save_settings_btn = tk.Button(
            region_info_frame,
            text="설정 저장",
            command=self.save_settings
        )

        self.select_capture_region_btn.pack(side=tk.RIGHT, padx=5)
        self.select_detect_region_btn.pack(side=tk.RIGHT, padx=5)
        self.save_settings_btn.pack(side=tk.RIGHT, padx=5)

        # 캡처 탭 설정
        self.setup_capture_tab()

        # 감지 탭 설정
        self.setup_detector_tab()

        # 저장된 영역이 있으면 표시
        if self.capture_region:
            self.update_capture_region_info(self.capture_region)
        if self.detect_region:
            self.update_detect_region_info(self.detect_region)

    def setup_capture_tab(self):
        # 메인 프레임
        main_frame = tk.Frame(self.capture_tab, padx=5, pady=5)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 제목 레이블
        title_label = tk.Label(main_frame, text="간편 화면 캡처",
                               font=("Arial", 14, "bold"))
        title_label.pack(pady=2)

        # 미리보기 프레임
        preview_frame = tk.Frame(main_frame, bd=1, relief=tk.GROOVE)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # 미리보기 이미지를 위한 레이블
        self.preview_label = tk.Label(preview_frame, text="최근 캡처한 화면이 여기에 표시됩니다",
                                      height=8, width=45, bg="lightgray")
        self.preview_label.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

        # 컨트롤 프레임
        control_frame = tk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=2)

        # 캡처 결과 메시지
        self.result_label = tk.Label(control_frame, text="", font=("Arial", 9))
        self.result_label.pack(pady=2)

        # 모드 상태 표시 레이블
        self.mode_label = tk.Label(control_frame, text="캡처 모드: 비활성화",
                                   font=("Arial", 9, "bold"), fg="red")
        self.mode_label.pack(pady=2)

        # 클립보드 내용 표시 프레임
        clipboard_frame = tk.LabelFrame(main_frame, text="현재 클립보드", padx=5, pady=5)
        clipboard_frame.pack(fill=tk.X, pady=3)

        # 현재 클립보드 내용 레이블
        self.clipboard_label = tk.Label(clipboard_frame, text="", font=("Arial", 9))
        self.clipboard_label.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # 설정 프레임 추가
        settings_frame = tk.LabelFrame(main_frame, text="캡처 설정", padx=10, pady=10)
        settings_frame.pack(fill=tk.X, pady=5)

        # 항상 위에 표시 체크박스
        self.always_on_top_var = tk.BooleanVar(value=self.always_on_top)
        always_on_top_chk = tk.Checkbutton(
            settings_frame,
            text="항상 위에 표시",
            variable=self.always_on_top_var,
            command=self.toggle_always_on_top
        )
        always_on_top_chk.pack(anchor=tk.W, pady=2)

        # 클립보드 내용을 파일명으로 사용 체크박스
        self.auto_copy_filename_var = tk.BooleanVar(value=self.auto_copy_filename)
        auto_copy_chk = tk.Checkbutton(
            settings_frame,
            text="클립보드 내용을 파일명으로 자동 사용",
            variable=self.auto_copy_filename_var
        )
        auto_copy_chk.pack(anchor=tk.W, pady=2)

        # 단축키 안내 레이블
        shortcut_label = tk.Label(
            main_frame,
            text="단축키: F11 - 캡처 모드 전환, Enter - 화면 캡처",
            font=("Arial", 9),
            fg="#666666"
        )
        shortcut_label.pack(pady=5)

        # 상태 표시 레이블
        self.capture_status_label = tk.Label(main_frame, text="", font=("Arial", 9), fg="#666666")
        self.capture_status_label.pack(pady=2)

        # 클립보드 자동 모니터링 시작
        self.start_clipboard_monitor()

    def setup_detector_tab(self):
        # 메인 프레임 (어두운 테마)
        main_frame = tk.Frame(self.detector_tab, bg="#1e1e1e")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 상태 표시 라벨
        self.detector_status_label = tk.Label(
            main_frame,
            text="감지 준비 완료",
            font=("맑은 고딕", 14),
            bg="#1e1e1e",
            fg="#ffffff"
        )
        self.detector_status_label.pack(pady=10)

        # 이미지 감지 결과 라벨
        self.detect_label = tk.Label(
            main_frame,
            text="",
            font=("맑은 고딕", 16, "bold"),
            bg="#1e1e1e",
            fg="#4CAF50"  # 녹색
        )
        self.detect_label.pack(pady=10)

        # 클립보드 복사 결과 표시 라벨
        self.copy_result_label = tk.Label(
            main_frame,
            text="",
            font=("맑은 고딕", 12),
            bg="#1e1e1e",
            fg="#FFEB3B"  # 노란색
        )
        self.copy_result_label.pack(pady=5)

        # 버튼 프레임
        button_frame = tk.Frame(main_frame, bg="#1e1e1e")
        button_frame.pack(pady=10)

        # 감지 시작/중지 버튼
        self.toggle_detection_btn = tk.Button(
            button_frame,
            text="감지 시작",
            font=("맑은 고딕", 12, "bold"),
            bg="#007BFF",
            fg="white",
            padx=10,
            pady=5,
            command=self.toggle_detection
        )
        self.toggle_detection_btn.pack(side=tk.LEFT, padx=5)

        # 이미지 목록 새로고침 버튼
        self.refresh_images_btn = tk.Button(
            button_frame,
            text="이미지 새로고침",
            font=("맑은 고딕", 12),
            bg="#28a745",
            fg="white",
            padx=10,
            pady=5,
            command=self.refresh_reference_images
        )
        self.refresh_images_btn.pack(side=tk.LEFT, padx=5)

        # 임계값 조절 프레임
        threshold_frame = tk.Frame(main_frame, bg="#1e1e1e")
        threshold_frame.pack(pady=10)

        # 임계값 라벨
        tk.Label(
            threshold_frame,
            text="인식 임계값:",
            font=("맑은 고딕", 10),
            bg="#1e1e1e",
            fg="#ffffff"
        ).pack(side=tk.LEFT, padx=5)

        # 임계값 설정 변수 및 슬라이더
        self.threshold_var = tk.DoubleVar(value=self.detection_threshold)
        self.threshold_slider = tk.Scale(
            threshold_frame,
            from_=0.5,
            to=0.95,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            length=150,
            variable=self.threshold_var,
            bg="#1e1e1e",
            fg="#ffffff",
            highlightthickness=0
        )
        self.threshold_slider.pack(side=tk.LEFT)

        # 감지된 이미지 목록 프레임
        images_frame = tk.LabelFrame(main_frame, text="감지 가능한 이미지", padx=10, pady=10, bg="#2a2a2a", fg="#ffffff")
        images_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 스크롤바가 있는 텍스트 영역
        self.image_list_text = tk.Text(images_frame, height=5, width=40, bg="#333333", fg="#ffffff")
        self.image_list_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(images_frame, command=self.image_list_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.image_list_text.config(yscrollcommand=scrollbar.set)

        # 현재 이미지 목록 표시
        self.update_image_list()

    def update_image_list(self):
        """감지 가능한 이미지 목록 업데이트"""
        self.image_list_text.config(state=tk.NORMAL)
        self.image_list_text.delete(1.0, tk.END)

        if not self.reference_images:
            self.image_list_text.insert(tk.END, f"감지 가능한 이미지가 없습니다.\n{DATA_FOLDER} 폴더에 PNG 이미지를 추가하세요.")
        else:
            self.image_list_text.insert(tk.END, f"총 {len(self.reference_images)}개의 이미지 감지 가능:\n\n")
            for name in sorted(self.reference_images.keys()):
                self.image_list_text.insert(tk.END, f"• {name}\n")

        self.image_list_text.config(state=tk.DISABLED)

    def load_reference_images(self):
        """DATA 폴더에서 모든 PNG 이미지를 불러와 이름과 함께 저장"""
        # 기존 이미지 목록 초기화
        self.reference_images = {}

        if not os.path.exists(DATA_FOLDER):
            os.makedirs(DATA_FOLDER)
            print(f"{DATA_FOLDER} 폴더 생성. 이미지를 추가해주세요.")
            return

        for filename in os.listdir(DATA_FOLDER):
            if filename.lower().endswith('.png'):
                try:
                    # PIL을 사용하여 이미지 로드 (한글 경로 지원)
                    image_path = os.path.join(DATA_FOLDER, filename)
                    name = os.path.splitext(filename)[0]  # 확장자 없는 파일명 가져오기

                    # PIL로 이미지 불러온 후 OpenCV 형식으로 변환
                    pil_image = Image.open(image_path)
                    image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

                    if image is not None:
                        self.reference_images[name] = image
                        print(f"이미지 로드: {name}")
                except Exception as e:
                    print(f"이미지 로드 실패 ({filename}): {e}")

        print(f"총 {len(self.reference_images)}개의 이미지 로드 완료")

    def refresh_reference_images(self):
        """이미지 목록 새로고침"""
        self.load_reference_images()
        self.update_image_list()
        self.detector_status_label.config(text="이미지 목록을 새로고침했습니다", fg="#4CAF50")
        # 2초 후 원래 메시지로 복귀
        self.root.after(2000, lambda: self.detector_status_label.config(text="감지 준비 완료", fg="#ffffff"))

    def toggle_detection(self):
        """이미지 감지 시작/중지 전환"""
        self.detection_active = not self.detection_active

        if self.detection_active:
            # 영역이 선택되지 않았으면 선택 요청
            if not self.detect_region:
                self.detector_status_label.config(text="감지할 영역을 먼저 선택해주세요", fg="#FFEB3B")
                self.detection_active = False
                return

            # 감지 시작
            self.toggle_detection_btn.config(text="감지 중지", bg="#dc3545")
            self.detector_status_label.config(text="이미지 감지 중...", fg="#4CAF50")

            # 감지 스레드가 없으면 생성
            if self.detection_thread is None or not self.detection_thread.is_alive():
                self.detection_thread = threading.Thread(target=self.detection_loop)
                self.detection_thread.daemon = True
                self.detection_thread.start()
        else:
            # 감지 중지
            self.toggle_detection_btn.config(text="감지 시작", bg="#007BFF")
            self.detector_status_label.config(text="감지 중지됨", fg="#ffffff")

    def detection_loop(self):
        """이미지 감지 루프"""
        while self.running and self.detection_active:
            try:
                if not self.detect_region:
                    # 선택된 영역이 없으면 일시 중지
                    time.sleep(0.5)
                    continue

                # 선택된 영역에서 x1, y1, x2, y2 추출
                x1, y1, x2, y2 = self.detect_region
                width = x2 - x1
                height = y2 - y1

                # 지정된 영역 캡처
                screenshot = pyautogui.screenshot(region=(x1, y1, width, height))

                # PIL 이미지를 OpenCV 형식으로 변환
                screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

                # 각 참조 이미지 확인
                best_match = None
                highest_confidence = 0

                # 참조 이미지가 없으면 건너뛰기
                if not self.reference_images:
                    time.sleep(0.1)
                    continue

                for name, ref_img in self.reference_images.items():
                    match_found, confidence, _ = self.detect_image(screenshot_cv, ref_img)

                    if match_found and confidence > highest_confidence:
                        highest_confidence = confidence
                        best_match = name

                # 이전 이름과 새로 감지된 이름 비교
                old_name = self.detected_name
                new_name = best_match if best_match else ""

                # 감지된 이름 업데이트
                self.detected_name = new_name

                # UI 업데이트 (메인 스레드에서 실행)
                if self.detected_name:
                    self.root.after(0, lambda: self.detect_label.config(
                        text=f"발견: {self.detected_name} ({highest_confidence:.2f})",
                        fg="#4CAF50"  # 녹색
                    ))

                    # 새 이미지가 감지되었고, 이전과 다르면 자동 복사
                    if self.detected_name != old_name and self.detected_name != self.last_copied_name:
                        self.root.after(0, lambda name=self.detected_name: self.copy_to_clipboard(name))
                else:
                    self.root.after(0, lambda: self.detect_label.config(
                        text="이미지 없음",
                        fg="#CCCCCC"  # 회색
                    ))

            except Exception as e:
                print(f"감지 오류: {e}")
                self.root.after(0, lambda: self.detector_status_label.config(text=f"오류 발생: {str(e)}", fg="#F44336"))

            # 루프 주기 (CPU 사용량 줄이기)
            time.sleep(0.1)

        # 루프 종료 시 UI 업데이트
        if not self.detection_active:
            self.root.after(0, lambda: self.detect_label.config(text=""))

    def detect_image(self, screenshot, reference_img):
        """
        템플릿 매칭을 사용하여 스크린샷에서 참조 이미지가 나타나는지 감지
        임계값을 UI에서 설정한 값으로 사용
        """
        threshold = self.threshold_var.get()  # UI에서 설정한 임계값 사용

        # 더 나은 매칭을 위해 이미지를 그레이스케일로 변환
        gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        gray_reference = cv2.cvtColor(reference_img, cv2.COLOR_BGR2GRAY)

        # 템플릿 매칭 적용
        result = cv2.matchTemplate(gray_screenshot, gray_reference, cv2.TM_CCOEFF_NORMED)

        # 최고 매칭 위치와 신뢰도 가져오기
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        # 신뢰도가 임계값보다 높으면 매칭으로 간주
        if max_val >= threshold:
            return True, max_val, max_loc

        return False, max_val, None

    def copy_to_clipboard(self, text):
        """텍스트를 클립보드에 복사"""
        # "물음표" 텍스트가 입력되면 "????"로 변환
        if text == "물음표":
            text = "????"
        pyperclip.copy(text)

        # 복사 결과 표시
        self.copy_result_label.config(text=f'"{text}" 클립보드에 복사됨')
        self.last_copied_name = text

        # 2초 후에 메시지 지우기
        self.root.after(2000, lambda: self.copy_result_label.config(text=""))

    def toggle_always_on_top(self):
        """항상 위에 표시 토글"""
        self.always_on_top = self.always_on_top_var.get()
        self.root.attributes("-topmost", self.always_on_top)

    def start_clipboard_monitor(self):
        """클립보드 내용을 주기적으로 확인하여 갱신"""
        self.update_clipboard_label()
        # 1초마다 클립보드 확인
        self.clipboard_timer = self.root.after(1000, self.start_clipboard_monitor)

    def update_clipboard_label(self):
        """클립보드 내용 표시 업데이트"""
        try:
            clipboard_text = pyperclip.paste()
            if clipboard_text:
                # 길이가 너무 길면 잘라서 표시
                if len(clipboard_text) > 30:
                    display_text = clipboard_text[:27] + "..."
                else:
                    display_text = clipboard_text
                self.clipboard_label.config(text=f"현재 클립보드: {display_text}")
            else:
                self.clipboard_label.config(text="클립보드가 비어있습니다")
        except Exception as e:
            self.clipboard_label.config(text=f"클립보드 읽기 오류: {str(e)}")

    def setup_global_hotkeys(self):
        """전역 키보드 단축키 설정"""
        # 기존 리스너가 있으면 종료
        if self.listener:
            self.listener.stop()

        # 키보드 콜백 함수
        def on_press(key):
            try:
                # F11 키 감지 - 캡처 모드 전환
                if key == keyboard.Key.f11:
                    self.toggle_capture_mode()
                # Enter 키 감지 - 캡처 실행
                elif key == keyboard.Key.enter:
                    self.capture_if_active()
            except Exception as e:
                print(f"키 처리 오류: {e}")

        # 리스너 생성
        self.listener = keyboard.Listener(on_press=on_press)
        self.listener.start()

    def toggle_capture_mode(self):
        """캡처 모드 전환"""
        self.capture_mode = not self.capture_mode

        if self.capture_mode:
            # 영역이 선택되지 않았다면 안내
            if not self.capture_region:
                self.mode_label.config(text="캡처 모드: 활성화 (영역 선택 필요)", fg="blue")
                self.result_label.config(text="캡처할 영역을 선택해주세요", fg="blue")
            else:
                self.mode_label.config(text="캡처 모드: 활성화", fg="green")
                self.result_label.config(text="Enter 키를 눌러 화면을 캡처하세요", fg="blue")
        else:
            # 캡처 모드 비활성화
            self.mode_label.config(text="캡처 모드: 비활성화", fg="red")
            self.result_label.config(text="", fg="black")

    def capture_if_active(self):
        """캡처 모드가 활성화된 경우 캡처 실행"""
        if self.capture_mode:
            # 영역이 선택되지 않았으면 선택 시작
            if not self.capture_region:
                self.start_capture_region_selection()
            else:
                # 이미 선택된 영역이 있으면 그 영역 캡처
                self.capture_screen()

    def start_capture_region_selection(self):
        """캡처 영역 선택 시작"""
        # 영역 선택기 표시 (캡처 타입)
        selector = ScreenshotRegionSelector(self.on_region_selected, "capture")
        selector.start_selection()

    def start_detect_region_selection(self):
        """감지 영역 선택 시작"""
        # 영역 선택기 표시 (감지 타입)
        selector = ScreenshotRegionSelector(self.on_region_selected, "detect")
        selector.start_selection()

    def on_region_selected(self, region, selection_type):
        """영역 선택 완료 후 처리"""
        if region:
            # 선택 타입에 따라 다른 영역에 저장
            if selection_type == "capture":
                self.capture_region = region
                self.update_capture_region_info(region)

                # 캡처 모드가 활성화된 경우 안내 메시지 업데이트
                if self.capture_mode:
                    self.result_label.config(text="Enter 키를 눌러 화면을 캡처하세요", fg="blue")

            elif selection_type == "detect":
                self.detect_region = region
                self.update_detect_region_info(region)

                # 감지 중이면 상태 메시지 업데이트
                if self.detection_active:
                    self.detector_status_label.config(text="새 영역이 선택되었습니다", fg="#4CAF50")

    def update_capture_region_info(self, region):
        """캡처 영역 정보 업데이트"""
        x1, y1, x2, y2 = region
        width = x2 - x1
        height = y2 - y1

        self.capture_region_info_label.config(
            text=f"캡처 범위: ({x1},{y1}) ~ ({x2},{y2}) [크기: {width}x{height}]"
        )

    def update_detect_region_info(self, region):
        """감지 영역 정보 업데이트"""
        x1, y1, x2, y2 = region
        width = x2 - x1
        height = y2 - y1

        self.detect_region_info_label.config(
            text=f"감지 범위: ({x1},{y1}) ~ ({x2},{y2}) [크기: {width}x{height}]"
        )

    def capture_screen(self):
        """선택된 영역 화면 캡처"""
        if not self.capture_region:
            self.result_label.config(text="캡처할 영역을 선택해주세요", fg="blue")
            self.start_capture_region_selection()
            return

        try:
            # 선택된 영역에서 좌표 추출
            x1, y1, x2, y2 = self.capture_region
            width = x2 - x1
            height = y2 - y1

            # 파일명 생성
            if self.auto_copy_filename_var.get():
                # 클립보드 내용을 파일명으로 사용
                clipboard_text = pyperclip.paste()
                if clipboard_text:
                    # 파일명으로 사용할 수 없는 문자 제거
                    filename = "".join([c for c in clipboard_text if c.isalnum() or c in (' ', '_', '-','.')])
                    # 공백 문자를 언더스코어로 변경
                    filename = filename.strip().replace(' ', '')

                    # 파일명이 비어있으면 현재 시간 사용
                    if not filename:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"screenshot_{timestamp}.png"
                    else:
                        # 파일명이 너무 길면 자르기
                        if len(filename) > 50:
                            filename = filename[:50]
                        filename = f"{filename}.png"
                else:
                    # 클립보드가 비어있으면 현재 시간으로 파일명 생성
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"screenshot_{timestamp}.png"
            else:
                # 시간만 사용하여 파일명 생성
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"

            filepath = os.path.join(self.save_path, filename)

            # 지정된 영역만 캡처
            screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            screenshot.save(filepath)

            # 캡처 결과 표시
            self.result_label.config(text=f"캡처 성공: {filename}", fg="green")

            # 미리보기 업데이트
            self.update_preview(filepath)

        except Exception as e:
            self.result_label.config(text=f"캡처 실패: {str(e)}", fg="red")
            print(f"캡처 실패: {str(e)}")

    def update_preview(self, image_path):
        """미리보기 이미지 업데이트"""
        try:
            img = Image.open(image_path)

            # 미리보기 영역 크기 가져오기
            preview_width = self.preview_label.winfo_width() - 20  # 패딩 고려
            preview_height = self.preview_label.winfo_height() - 20  # 패딩 고려

            # 크기가 0이면 기본값 설정
            if preview_width <= 0:
                preview_width = 450
            if preview_height <= 0:
                preview_height = 250

            # 이미지 비율 유지하면서 리사이즈
            img_width, img_height = img.size
            ratio = min(preview_width / img_width, preview_height / img_height)
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)

            img = img.resize((new_width, new_height), Image.LANCZOS)
            img_tk = ImageTk.PhotoImage(img)

            self.preview_label.config(image=img_tk, text="")  # 텍스트 제거
            self.preview_label.image = img_tk  # 참조 유지
        except Exception as e:
            print(f"미리보기 업데이트 실패: {e}")
            self.preview_label.config(text=f"미리보기 로드 실패: {str(e)}", image="")

    def save_settings(self):
        """현재 설정을 JSON 파일로 저장"""
        try:
            # 현재 UI 값에서 설정 업데이트
            self.always_on_top = self.always_on_top_var.get()
            self.auto_copy_filename = self.auto_copy_filename_var.get()
            self.detection_threshold = self.threshold_var.get()

            settings = {
                "always_on_top": self.always_on_top,
                "auto_copy_filename": self.auto_copy_filename,
                "detection_threshold": self.detection_threshold,
                "capture_region": self.capture_region,  # 캡처 영역 저장
                "detect_region": self.detect_region  # 감지 영역 저장
            }

            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)

            # 캡처 탭에 저장 성공 메시지
            self.capture_status_label.config(text="설정이 저장되었습니다", fg="green")
            # 3초 후에 메시지 지우기
            self.root.after(3000, lambda: self.capture_status_label.config(text=""))

            # 감지 탭에도 저장 성공 메시지
            self.detector_status_label.config(text="설정이 저장되었습니다", fg="#4CAF50")
            # 3초 후에 메시지 지우기
            self.root.after(3000, lambda: self.detector_status_label.config(
                text="감지 준비 완료" if not self.detection_active else "이미지 감지 중...", fg="#ffffff"))

            print("설정 저장 완료")

        except Exception as e:
            # 저장 실패 메시지
            self.capture_status_label.config(text=f"설정 저장 실패: {str(e)}", fg="red")
            self.detector_status_label.config(text=f"설정 저장 실패: {str(e)}", fg="#F44336")
            print(f"설정 저장 오류: {e}")

    def load_settings(self):
        """저장된 설정 불러오기"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

                # 설정 적용
                self.always_on_top = settings.get("always_on_top", True)
                self.auto_copy_filename = settings.get("auto_copy_filename", True)
                self.detection_threshold = settings.get("detection_threshold", 0.8)

                # 캡처 영역과 감지 영역 불러오기
                self.capture_region = settings.get("capture_region")
                self.detect_region = settings.get("detect_region")

                print("설정 불러오기 완료")
                return True
        except Exception as e:
            print(f"설정 불러오기 오류: {e}")

        return False

    def on_close(self):
        """종료 시 정리 작업"""
        # 설정 저장
        self.save_settings()

        # 감지 중지
        self.detection_active = False
        self.running = False

        # 타이머 정리
        if self.clipboard_timer:
            self.root.after_cancel(self.clipboard_timer)

        # 리스너 정리
        if self.listener:
            self.listener.stop()

        # 창 종료
        self.root.destroy()


if __name__ == "__main__":
    # GUI 모드로 실행
    root = tk.Tk()
    app = CombinedApp(root)
    root.mainloop()