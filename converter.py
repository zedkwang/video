import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import threading
import time
import queue
import webbrowser
import platform

# 버전 정보
APP_VERSION = "1.0.0"
APP_NAME = "다중 파일 동영상 변환기 (HEVC/H.265)"

# 자동 업데이트 확인 URL (GitHub Releases 페이지 등으로 설정 가능)
UPDATE_URL = "https://github.com/yourusername/video-converter/releases"

# 의존성 확인 및 설치 함수
def check_dependencies():
    missing_packages = []
    
    # PIL 확인
    try:
        from PIL import Image
        if not hasattr(Image, 'ANTIALIAS'):
            # Pillow 9.0.0부터 ANTIALIAS가 삭제되고 LANCZOS로 대체됨
            Image.ANTIALIAS = Image.LANCZOS
        print("PIL 확인: 성공")
    except ImportError:
        missing_packages.append("pillow")
    
    # MoviePy 확인
    try:
        import moviepy
        print(f"MoviePy 확인: 성공 (버전 {moviepy.__version__})")
        
        # 필요한 모듈 확인
        try:
            from moviepy.video.io.VideoFileClip import VideoFileClip
        except ImportError:
            try:
                import moviepy.editor
                from moviepy.editor import VideoFileClip
            except ImportError:
                # 설치되어 있지만 문제가 있는 경우 재설치 필요
                missing_packages.append("moviepy")
    except ImportError:
        missing_packages.append("moviepy")
    
    # 패키지 설치가 필요한 경우
    if missing_packages:
        if messagebox.askyesno("필수 라이브러리 설치", 
                           f"이 프로그램을 실행하기 위해 다음 패키지를 설치해야 합니다:\n{', '.join(missing_packages)}\n\n자동으로 설치하시겠습니까?"):
            try:
                import subprocess
                for package in missing_packages:
                    if package == "moviepy":
                        # MoviePy는 특정 버전으로 설치
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "moviepy==1.0.3"])
                    else:
                        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                
                messagebox.showinfo("설치 완료", "필수 라이브러리 설치가 완료되었습니다. 프로그램을 다시 시작해주세요.")
                sys.exit(0)
            except Exception as e:
                messagebox.showerror("설치 오류", f"패키지 설치 중 오류가 발생했습니다:\n{e}\n\n수동으로 설치하려면 터미널에서 다음 명령어를 실행하세요:\npip install pillow moviepy==1.0.3")
                sys.exit(1)
        else:
            sys.exit(1)
    
    # Mac에서 FFMPEG 시간 초과 방지를 위한 설정
    try:
        import moviepy.config as mpconf
        # FFMPEG 명령어 타임아웃 증가 (기본값은 종종 부족함)
        mpconf.FFMPEG_BINARY_TIMEOUT = 60  # 초 단위, 필요에 따라 조정
    except:
        pass


class MultiFileVideoConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)
        
        # 시스템 확인
        self.system = platform.system()  # 'Windows', 'Darwin' (Mac), 'Linux'
        
        # 최대 파일 개수 변수
        self.MAX_FILES = 100
        
        # 변수 초기화
        self.video_files = []  # 선택한 비디오 파일 목록
        self.output_video_paths = []  # 변환된 비디오 파일 경로
        self.fps_var = tk.IntVar(value=30)  # 기본값 30fps
        self.bitrate_var = tk.IntVar(value=300)  # 300kbps 고정
        self.conversion_thread = None
        self.conversion_queue = queue.Queue()  # 변환 대기열
        self.stop_conversion = False
        
        # 총 비디오 시간 추적을 위한 변수
        self.total_video_duration = 0
        self.video_durations = {}  # 파일 경로를 키로, 길이를 값으로 저장
        
        # 다운로드 경로 설정
        self.download_path = os.path.expanduser("~/Downloads")
        
        # 해상도 설정 변수 (360p 기본값)
        self.resolution_var = tk.IntVar(value=360)
        
        # 출력 폴더 변경 가능하도록 설정
        self.output_folder_var = tk.StringVar(value=self.download_path)
        
        # 메뉴 바 생성
        self.create_menu_bar()
        
        # 메인 프레임
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 왼쪽 패널
        left_panel = ttk.Frame(main_frame, width=350)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        
        # 파일 선택 프레임
        file_frame = ttk.LabelFrame(left_panel, text="파일 선택", padding="10")
        file_frame.pack(fill=tk.X, pady=(0, 10))
        
        select_btn = ttk.Button(file_frame, text=f"동영상 파일 선택 (최대 {self.MAX_FILES}개)", command=self.select_files)
        select_btn.pack(fill=tk.X)
        
        # 파일 카운터 표시
        self.file_count_var = tk.StringVar(value="0개 파일 선택됨")
        file_count_label = ttk.Label(file_frame, textvariable=self.file_count_var)
        file_count_label.pack(anchor=tk.E, pady=(5, 0))
        
        # 출력 폴더 선택
        output_folder_frame = ttk.Frame(file_frame)
        output_folder_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(output_folder_frame, text="출력 폴더:").pack(side=tk.LEFT)
        ttk.Entry(output_folder_frame, textvariable=self.output_folder_var, width=30).pack(side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True)
        ttk.Button(output_folder_frame, text="찾아보기", command=self.select_output_folder).pack(side=tk.RIGHT)
        
        # 파일 목록 프레임
        file_list_frame = ttk.LabelFrame(left_panel, text="선택된 파일 목록", padding="10")
        file_list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 파일 목록 표시 (Treeview)
        self.file_list = ttk.Treeview(file_list_frame, columns=("size", "duration", "fps"), height=10)
        self.file_list.heading("#0", text="파일명")
        self.file_list.heading("size", text="크기")
        self.file_list.heading("duration", text="길이")
        self.file_list.heading("fps", text="FPS")
        self.file_list.column("#0", width=180)
        self.file_list.column("size", width=70, anchor="center")
        self.file_list.column("duration", width=70, anchor="center")
        self.file_list.column("fps", width=50, anchor="center")
        self.file_list.pack(fill=tk.BOTH, expand=True)
        
        # 파일 목록 스크롤바
        file_list_scrollbar = ttk.Scrollbar(self.file_list, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=file_list_scrollbar.set)
        file_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 선택된 파일 제거 버튼
        remove_btn = ttk.Button(file_list_frame, text="선택된 파일 제거", command=self.remove_selected_file)
        remove_btn.pack(fill=tk.X, pady=(5, 0))
        
        # 모든 파일 제거 버튼
        clear_btn = ttk.Button(file_list_frame, text="모든 파일 제거", command=self.clear_file_list)
        clear_btn.pack(fill=tk.X, pady=(5, 0))
        
        # 변환 설정 프레임
        settings_frame = ttk.LabelFrame(left_panel, text="변환 설정", padding="10")
        settings_frame.pack(fill=tk.X, pady=(0, 10))
        
        # FPS 설정 (24fps 또는 30fps)
        ttk.Label(settings_frame, text="프레임 레이트 (FPS):").pack(anchor=tk.W, pady=(0, 5))
        fps_frame = ttk.Frame(settings_frame)
        fps_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Radiobutton(fps_frame, text="30 FPS", variable=self.fps_var, value=30).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(fps_frame, text="24 FPS", variable=self.fps_var, value=24).pack(side=tk.LEFT)
        
        # 해상도 설정 (360p, 480p, 720p, 1080p)
        ttk.Label(settings_frame, text="해상도:").pack(anchor=tk.W, pady=(0, 5))
        resolution_frame = ttk.Frame(settings_frame)
        resolution_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Radiobutton(resolution_frame, text="360p", variable=self.resolution_var, value=360).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(resolution_frame, text="480p", variable=self.resolution_var, value=480).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(resolution_frame, text="720p", variable=self.resolution_var, value=720).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(resolution_frame, text="1080p", variable=self.resolution_var, value=1080).pack(side=tk.LEFT)
        
        # 고정 설정 정보
        fixed_settings_frame = ttk.Frame(settings_frame)
        fixed_settings_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(fixed_settings_frame, text="인코딩 설정:", font=("", 9, "bold")).pack(anchor=tk.W)
        ttk.Label(fixed_settings_frame, text="• 코덱: HEVC/H.265").pack(anchor=tk.W, padx=(10, 0))
        ttk.Label(fixed_settings_frame, text="• 해상도별 최적화된 비트레이트").pack(anchor=tk.W, padx=(10, 0))
        
        # 변환 버튼 영역
        button_frame = ttk.Frame(settings_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 변환 버튼
        self.convert_btn = ttk.Button(button_frame, text="모든 파일 변환 시작", command=self.start_conversion, state=tk.DISABLED)
        self.convert_btn.pack(fill=tk.X, pady=(0, 5))
        
        # 중지 버튼
        self.stop_btn = ttk.Button(button_frame, text="변환 중지", command=self.stop_conversion_process, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X)
        
        # 오른쪽 패널
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 로그 영역
        log_frame = ttk.LabelFrame(right_panel, text="변환 로그", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 로그 스크롤바
        log_scrollbar = ttk.Scrollbar(self.log_text, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 변환 진행 상황
        progress_frame = ttk.LabelFrame(right_panel, text="변환 진행 상황", padding="10")
        progress_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 전체 진행 상황
        ttk.Label(progress_frame, text="전체 진행 상황:").pack(anchor=tk.W)
        self.total_progress_var = tk.DoubleVar(value=0.0)
        self.total_progress_bar = ttk.Progressbar(progress_frame, variable=self.total_progress_var, length=100)
        self.total_progress_bar.pack(fill=tk.X, pady=(0, 5))
        
        self.total_progress_label = ttk.Label(progress_frame, text="0/0 파일 완료 (0%)")
        self.total_progress_label.pack(anchor=tk.E, pady=(0, 10))
        
        # 현재 파일 진행 상황
        ttk.Label(progress_frame, text="현재 파일:").pack(anchor=tk.W)
        self.current_file_label = ttk.Label(progress_frame, text="대기 중...")
        self.current_file_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.file_progress_var = tk.DoubleVar(value=0.0)
        self.file_progress_bar = ttk.Progressbar(progress_frame, variable=self.file_progress_var, length=100)
        self.file_progress_bar.pack(fill=tk.X)
        
        # 출력 폴더 열기 버튼
        self.open_folder_btn = ttk.Button(progress_frame, text="출력 폴더 열기", command=self.open_output_folder)
        self.open_folder_btn.pack(fill=tk.X, pady=(10, 0))
        
        # 상태 바
        self.status_var = tk.StringVar(value="준비")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(5, 2))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        # 초기 메시지
        self.log(f"{APP_NAME} v{APP_VERSION}이 시작되었습니다.")
        self.log(f"운영 체제: {self.system}")
        self.log(f"최대 {self.MAX_FILES}개 파일을 동시에 선택할 수 있습니다.")
        self.log("설정: HEVC/H.265 코덱, 해상도별 최적화된 비트레이트")
        self.log(f"변환된 파일은 다음 경로에 저장됩니다: {self.download_path}")
        
        # 업데이트 확인
        self.check_for_updates()
    
    def create_menu_bar(self):
        """메뉴 바 생성"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 파일 메뉴
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="파일", menu=file_menu)
        file_menu.add_command(label="파일 선택", command=self.select_files)
        file_menu.add_command(label="출력 폴더 선택", command=self.select_output_folder)
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self.root.quit)
        
        # 도구 메뉴
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="도구", menu=tools_menu)
        tools_menu.add_command(label="모든 파일 제거", command=self.clear_file_list)
        tools_menu.add_command(label="출력 폴더 열기", command=self.open_output_folder)
        tools_menu.add_separator()
        tools_menu.add_command(label="설정 초기화", command=self.reset_settings)
        
        # 도움말 메뉴
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="도움말", menu=help_menu)
        help_menu.add_command(label="사용 설명서", command=self.show_help)
        help_menu.add_command(label="업데이트 확인", command=self.check_for_updates)
        help_menu.add_separator()
        help_menu.add_command(label="정보", command=self.show_about)
    
    def check_for_updates(self):
        """업데이트 확인 (실제 구현 시 서버 연결 필요)"""
        # 실제 구현 시에는 서버에서 최신 버전 정보를 가져와 비교
        # 여기서는 간단한 예시로 작성
        self.log("업데이트 확인 중...")
        
        # 실제 업데이트 체크 로직은 별도 스레드로 실행
        def check_update_thread():
            # 여기서는 항상 최신 버전이라고 가정
            time.sleep(1)  # 서버 응답 시간 시뮬레이션
            self.log("현재 최신 버전을 사용 중입니다.")
        
        threading.Thread(target=check_update_thread, daemon=True).start()
    
    def show_help(self):
        """도움말 표시"""
        help_text = """
사용 방법:

1. '동영상 파일 선택' 버튼을 클릭하여 변환할 파일을 선택합니다.
2. 원하는 프레임 레이트와 해상도를 선택합니다.
3. '모든 파일 변환 시작' 버튼을 클릭하여 변환을 시작합니다.
4. 변환된 파일은 선택한 출력 폴더에 저장됩니다.

문제가 발생하면 로그를 확인하세요.
        """
        messagebox.showinfo("사용 설명서", help_text)
    
    def show_about(self):
        """프로그램 정보 표시"""
        about_text = f"""
{APP_NAME} v{APP_VERSION}

동영상 파일을 HEVC/H.265 코덱으로 변환하는 프로그램입니다.
다양한 해상도와 프레임 레이트 옵션을 제공합니다.

© 2024 개발자 이름
        """
        messagebox.showinfo("정보", about_text)
    
    def reset_settings(self):
        """설정 초기화"""
        if messagebox.askyesno("설정 초기화", "모든 설정을 기본값으로 되돌리시겠습니까?"):
            self.fps_var.set(30)
            self.resolution_var.set(360)
            self.output_folder_var.set(self.download_path)
            self.log("설정이 초기화되었습니다.")
    
    def select_output_folder(self):
        """출력 폴더 선택"""
        folder_path = filedialog.askdirectory(title="변환된 파일을 저장할 폴더 선택")
        if folder_path:
            self.output_folder_var.set(folder_path)
            self.log(f"출력 폴더 변경됨: {folder_path}")
    
    def open_output_folder(self):
        """출력 폴더 열기"""
        folder_path = self.output_folder_var.get()
        
        if not os.path.exists(folder_path):
            messagebox.showwarning("경고", "지정된 출력 폴더가 존재하지 않습니다.")
            return
        
        try:
            # 운영 체제에 따라 폴더 열기 방식 다르게 적용
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.call(["open", folder_path])
            else:  # Linux
                subprocess.call(["xdg-open", folder_path])
        except Exception as e:
            messagebox.showerror("오류", f"폴더를 열 수 없습니다: {e}")
    
    def log(self, message):
        """로그 메시지 추가"""
        self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def select_files(self):
        """여러 동영상 파일 선택"""
        filetypes = [
            ("비디오 파일", "*.mp4 *.avi *.mov *.mkv *.webm *.flv"),
            ("모든 파일", "*.*")
        ]
        
        try:
            file_paths = filedialog.askopenfilenames(
                title=f"변환할 동영상 파일 선택 (최대 {self.MAX_FILES}개)",
                filetypes=filetypes
            )
        except Exception as e:
            self.log(f"파일 선택 오류: {e}")
            messagebox.showerror("오류", f"파일 선택 대화상자를 열 수 없습니다: {e}")
            return
            
        if not file_paths:
            return
        
        # 최대 파일 개수 제한
        existing_count = len(self.video_files)
        new_files = list(file_paths)
        
        # 이미 최대 개수 이상의 파일이 있는지 확인
        if existing_count >= self.MAX_FILES:
            messagebox.showinfo("알림", f"이미 최대 개수({self.MAX_FILES}개)의 파일이 선택되었습니다.")
            return
        
        # 남은 슬롯에 맞게 파일 추가
        available_slots = self.MAX_FILES - existing_count
        if len(new_files) > available_slots:
            new_files = new_files[:available_slots]
            messagebox.showinfo("알림", f"최대 {self.MAX_FILES}개까지만 선택 가능합니다. 처음 {available_slots}개 파일만 추가됩니다.")
        
        # 파일 목록에 추가
        for file_path in new_files:
            # 이미 목록에 있는지 확인
            if file_path in self.video_files:
                continue
                
            self.video_files.append(file_path)
            
            # 파일 정보 추출
            try:
                file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                
                # 비디오 길이 추출 (별도 스레드로 실행하여 UI 멈춤 방지)
                threading.Thread(target=self.add_file_to_list, args=(file_path, file_size), daemon=True).start()
                
                self.log(f"파일 추가됨: {Path(file_path).name}")
            except Exception as e:
                self.log(f"파일 정보 추출 오류: {e}")
        
        # 파일 개수 업데이트
        self.update_file_count()
        
        # 변환 버튼 상태 업데이트
        if self.video_files:
            self.convert_btn.config(state=tk.NORMAL)
        else:
            self.convert_btn.config(state=tk.DISABLED)
    
    def update_file_count(self):
        """파일 카운터 업데이트"""
        count = len(self.video_files)
        self.file_count_var.set(f"{count}개 파일 선택됨 (최대 {self.MAX_FILES}개)")
    
    def add_file_to_list(self, file_path, file_size):
        """파일 목록에 파일 정보 추가 (별도 스레드에서 실행)"""
        try:
            # 파일명
            file_name = Path(file_path).name
            
            # 비디오 길이 및 FPS 추출 (시간이 걸릴 수 있음)
            try:
                # 필요한 모듈 임포트
                from moviepy.video.io.VideoFileClip import VideoFileClip
                
                # Mac에서는 타임아웃 문제 방지를 위해 파라미터 조정
                clip = VideoFileClip(file_path, verbose=False, audio=False, has_mask=False)
                duration = clip.duration  # 초 단위
                fps = clip.fps  # 원본 FPS
                
                # 파일 경로와 길이 저장
                self.video_durations[file_path] = duration
                
                # 시간 포맷팅 (HH:MM:SS)
                hours, remainder = divmod(int(duration), 3600)
                minutes, seconds = divmod(remainder, 60)
                duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
                clip.close()
                
                # 성공적으로 파일 로드 완료 로깅
                self.log(f"파일 정보 로드 성공: {file_name}")
                
            except Exception as e:
                duration_str = "알 수 없음"
                fps = "?"
                self.video_durations[file_path] = 0  # 오류 발생 시 0으로 설정
                self.log(f"동영상 정보 추출 오류: {file_name} - {e}")
                self.log(f"동영상 정보를 읽을 수 없어도 변환은 가능합니다.")
            
            # UI 스레드에서 안전하게 업데이트
            self.root.after(0, lambda: self.file_list.insert("", "end", text=file_name, 
                                                       values=(f"{file_size:.1f} MB", duration_str, f"{fps:.1f}" if isinstance(fps, float) else fps)))
        except Exception as e:
            self.log(f"파일 목록 추가 오류: {e}")
    
    def remove_selected_file(self):
        """선택된 파일 제거"""
        selected_items = self.file_list.selection()
        if not selected_items:
            messagebox.showinfo("알림", "제거할 파일을 선택해주세요.")
            return
        
        for item in selected_items:
            file_name = self.file_list.item(item, "text")
            # 목록에서 해당 파일 찾기
            for file_path in self.video_files[:]:
                if Path(file_path).name == file_name:
                    self.video_files.remove(file_path)
                    # 영상 길이 정보도 제거
                    if file_path in self.video_durations:
                        del self.video_durations[file_path]
                    self.log(f"파일 제거됨: {file_name}")
                    break
            
            # 트리뷰에서 삭제
            self.file_list.delete(item)
        
        # 파일 개수 업데이트
        self.update_file_count()
        
        # 변환 버튼 상태 업데이트
        if self.video_files:
            self.convert_btn.config(state=tk.NORMAL)
        else:
            self.convert_btn.config(state=tk.DISABLED)
    
    def clear_file_list(self):
        """모든 파일 제거"""
        if not self.video_files:
            return
            
        self.video_files.clear()
        self.video_durations.clear()  # 영상 길이 정보도 모두 제거
        self.file_list.delete(*self.file_list.get_children())
        self.log("모든 파일이 제거되었습니다.")
        self.convert_btn.config(state=tk.DISABLED)
        
        # 파일 개수 업데이트
        self.update_file_count()
    
    def stop_conversion_process(self):
        """변환 중지"""
        if messagebox.askyesno("변환 중지", "현재 진행 중인 변환을 중지하시겠습니까?"):
            self.stop_conversion = True
            self.status_var.set("변환 중지 중...")
            self.log("변환 중지 요청됨. 현재 파일이 완료된 후 중지됩니다.")
    
    def start_conversion(self):
        """변환 시작"""
        if not self.video_files:
            messagebox.showinfo("알림", "변환할 동영상 파일을 먼저 선택해주세요.")
            return
        
        # 출력 폴더 확인
        output_folder = self.output_folder_var.get()
        if not os.path.exists(output_folder):
            if messagebox.askyesno("폴더 생성", f"선택한 출력 폴더가 존재하지 않습니다:\n{output_folder}\n\n폴더를 생성하시겠습니까?"):
                try:
                    os.makedirs(output_folder)
                except Exception as e:
                    messagebox.showerror("오류", f"폴더 생성 중 오류가 발생했습니다: {e}")
                    return
            else:
                return
        
        # UI 업데이트
        self.convert_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.stop_conversion = False
        self.output_video_paths = []
        
        # 총 비디오 시간 계산
        self.total_video_duration = sum(self.video_durations.values())
        
        # 변환 큐 초기화
        self.conversion_queue = queue.Queue()
        for file_path in self.video_files:
            self.conversion_queue.put(file_path)
        
        # 진행 상황 초기화
        self.total_progress_var.set(0)
        self.file_progress_var.set(0)
        total_files = len(self.video_files)
        self.total_progress_label.config(text=f"0/{total_files} 파일 완료 (0%)")
        self.current_file_label.config(text="대기 중...")
        
        # 변환 설정 정보 로깅
        fps = self.fps_var.get()
        resolution = self.resolution_var.get()
        
        # 총 비디오 시간 로깅
        hours, remainder = divmod(int(self.total_video_duration), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.log(f"총 작업 영상 시간: {int(self.total_video_duration)}초 ({hours}시간 {minutes}분 {seconds}초)")
        
        self.log(f"변환 시작: 총 {total_files}개 파일, 해상도={resolution}p, 프레임={fps}fps, 코덱=HEVC/H.265")
        self.status_var.set("변환 중...")
        
        # 별도 스레드에서 변환 실행
        self.conversion_thread = threading.Thread(target=self.process_conversion_queue, daemon=True)
        self.conversion_thread.start()
    
    def process_conversion_queue(self):
        """변환 큐 처리"""
        total_files = len(self.video_files)
        completed_files = 0
        completed_duration = 0  # 완료된 영상의 총 길이 (초)
        
        while not self.conversion_queue.empty() and not self.stop_conversion:
            file_path = self.conversion_queue.get()
            file_name = Path(file_path).name
            
            # 현재 진행 상황 업데이트
            self.root.after(0, lambda name=file_name: self.current_file_label.config(text=name))
            self.root.after(0, lambda: self.file_progress_var.set(0))
            
            # 현재 파일 길이
            current_duration = self.video_durations.get(file_path, 0)
            
            # 파일 변환
            try:
                self.log(f"파일 변환 시작: {file_name}")
                output_path = self.convert_single_file(file_path)
                if output_path:
                    self.output_video_paths.append(output_path)
                    completed_files += 1
                    completed_duration += current_duration
                    self.log(f"파일 변환 완료: {file_name} -> {Path(output_path).name}")
                else:
                    self.log(f"파일 변환 실패: {file_name}")
            except Exception as e:
                self.log(f"파일 변환 오류: {file_name} - {e}")
            
            # 전체 진행 상황 업데이트
            progress_percent = (completed_files / total_files) * 100
            self.root.after(0, lambda p=progress_percent: self.total_progress_var.set(p))
            self.root.after(0, lambda c=completed_files, t=total_files, p=progress_percent: 
                           self.total_progress_label.config(text=f"{c}/{t} 파일 완료 ({p:.1f}%)"))
            
            self.conversion_queue.task_done()
        
        # 변환 완료 또는 중단
        if self.stop_conversion:
            self.root.after(0, lambda: self.log("변환이 중단되었습니다."))
            self.root.after(0, lambda: self.status_var.set("변환 중단됨"))
        else:
            # 영상 길이 총합 계산
            seconds = int(completed_duration)
            minutes = seconds // 60
            hours = minutes // 60
            minutes %= 60
            
            self.root.after(0, lambda: self.log(f"모든 파일 변환 완료: {completed_files}/{total_files} 파일 성공"))
            self.root.after(0, lambda: self.log(f"작업 완료 영상 시간: {seconds}초 ({hours}시간 {minutes}분)"))
            self.root.after(0, lambda: self.status_var.set("변환 완료"))
            
            if self.output_video_paths:
                message = f"{completed_files}개 파일 변환 완료!\n저장 위치: {self.output_folder_var.get()}\n총 영상 시간: {hours}시간 {minutes}분 ({seconds}초)"
                self.root.after(0, lambda msg=message: messagebox.showinfo("변환 완료", msg))
        
        # UI 업데이트
        self.root.after(0, lambda: self.convert_btn.config(state=tk.NORMAL))
        self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))
        self.root.after(0, lambda: self.current_file_label.config(text="대기 중..."))
    
    def convert_single_file(self, file_path):
        """단일 파일 변환 처리 - FFMPEG 고급 매개변수 적용"""
        try:
            # 변환 설정 가져오기
            fps = self.fps_var.get()  # 사용자 선택 FPS (24 또는 30)
            height = self.resolution_var.get()  # 사용자 선택 해상도
            
            # 출력 폴더 가져오기
            output_folder = self.output_folder_var.get()
            
            # 출력 파일 경로
            input_file = Path(file_path)
            output_filename = f"{input_file.stem}_{height}p_{fps}fps.mp4"
            output_path = os.path.join(output_folder, output_filename)
            
            # 파일명 중복 확인 및 처리
            counter = 1
            while os.path.exists(output_path):
                output_filename = f"{input_file.stem}_{height}p_{fps}fps_{counter}.mp4"
                output_path = os.path.join(output_folder, output_filename)
                counter += 1
            
            # 진행 상황 업데이트
            self.root.after(0, lambda: self.log(f"동영상 로드 중: {input_file.name}"))
            
            # 원본 비디오 로드 - Mac에서는 타임아웃 문제를 방지하기 위해 파라미터 조정
            try:
                # 필요한 모듈 임포트
                from moviepy.video.io.VideoFileClip import VideoFileClip
                
                # Mac에서 성능 향상을 위한 옵션
                clip = VideoFileClip(file_path, 
                                     verbose=False,  # 상세 로그 끄기
                                     audio=True,     # 오디오 포함
                                     has_mask=False, # 마스크 처리 건너뛰기
                                     bufsize=4096)   # 버퍼 크기 증가
                
                self.root.after(0, lambda: self.log(f"파일을 성공적으로 불러왔습니다: {input_file.name}"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"파일 로드 오류: {err}"))
                self.root.after(0, lambda: self.log("외부 FFMPEG 프로세스를 직접 사용하는 방식으로 전환합니다."))
                
                # FFMPEG를 직접 호출하는 대체 방식 사용
                import subprocess
                
                self.root.after(0, lambda: self.log("대체 방식으로 파일 변환을 시도합니다..."))
                
                # 출력 파일 생성
                temp_output_path = output_path
                
                # FFMPEG 명령어 구성 - 요청한 HEVC/H.265 파라미터와 일치하도록 설정
                # 해상도에 따른 최적 파라미터 선택
                if height == 1080:
                    bitrate = "2.5M"
                    maxrate = "2.75M"
                    bufsize = "5M"
                    crf = "24"
                elif height == 720:
                    bitrate = "1.8M"
                    maxrate = "2.0M"
                    bufsize = "3.6M"
                    crf = "24"
                elif height == 480:
                    bitrate = "1.0M"
                    maxrate = "1.2M"
                    bufsize = "2.0M"
                    crf = "24"
                else:  # 360p 또는 기타 해상도
                    bitrate = "0.3M"
                    maxrate = "0.4M"
                    bufsize = "0.8M"
                    crf = "26"
                
                # 운영 체제에 따라 최적의 코덱 선택
                if platform.system() == "Windows":
                    codec = "libx265"  # Windows는 H.265 지원이 더 좋음
                    profile = "main"
                    codec_tag = "hvc1"
                else:  # Mac 및 Linux
                    # Mac에서는 H.264가 더 안정적일 수 있음
                    codec = "libx264"
                    profile = "high"
                    codec_tag = "avc1"
                
                # FFMPEG 기본 명령어
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-i", file_path,
                    "-vf", f"scale=-2:{height}",
                    "-r", str(fps),
                    "-c:v", codec,
                    "-profile:v", profile,
                    "-level:v", "4.1",
                    "-b:v", bitrate,
                    "-maxrate", maxrate,
                    "-bufsize", bufsize,
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    "-preset", "medium",
                    "-crf", crf,
                    temp_output_path
                ]
                
                # FFMPEG 프로세스 실행
                try:
                    process = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True
                    )
                    
                    # 진행 상황 모니터링을 위한 변수
                    progress_values = {"value": 0, "last_update": time.time()}
                    
                    # 진행 상황 모니터링 함수
                    def monitor_ffmpeg_progress():
                        elapsed_time = time.time() - progress_values["last_update"]
                        if elapsed_time > 1:  # 1초마다 업데이트
                            progress_values["value"] += 2  # 임의로 2%씩 증가
                            progress_values["value"] = min(progress_values["value"], 99)
                            progress_values["last_update"] = time.time()
                            self.root.after(0, lambda v=progress_values["value"]: self.file_progress_var.set(v))
                        
                        # 프로세스가 아직 실행 중인지 확인
                        if process.poll() is None and not self.stop_conversion:
                            self.root.after(500, monitor_ffmpeg_progress)
                    
                    # 모니터링 시작
                    self.root.after(0, monitor_ffmpeg_progress)
                    
                    # 프로세스가 완료될 때까지 대기
                    stdout, stderr = process.communicate()
                    
                    # 프로세스가 정상적으로 완료되었는지 확인
                    if process.returncode == 0:
                        # 파일 진행 상황 100%로 설정
                        self.root.after(0, lambda: self.file_progress_var.set(100))
                        
                        # 결과 파일 크기 확인
                        if os.path.exists(temp_output_path):
                            converted_size = os.path.getsize(temp_output_path) / (1024 * 1024)  # MB
                            original_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                            reduction = (1 - converted_size / original_size) * 100  # 감소율 %
                            
                            # 결과 로깅
                            self.root.after(0, lambda o=original_size, c=converted_size, r=reduction:
                                        self.log(f"변환 결과: {o:.1f} MB → {c:.1f} MB ({r:.1f}% 감소)"))
                            
                            return temp_output_path
                        else:
                            self.root.after(0, lambda: self.log("변환된 파일을 찾을 수 없습니다."))
                            return None
                    else:
                        self.root.after(0, lambda: self.log(f"FFMPEG 오류: {stderr}"))
                        return None
                
                except Exception as e:
                    self.root.after(0, lambda err=str(e): self.log(f"FFMPEG 실행 오류: {err}"))
                    return None
                
                return None
            
            # 진행 상황 업데이트
            self.root.after(0, lambda: self.log(f"해상도 변경 중: {input_file.name} -> {height}p"))
            
            # 해상도 변경
            try:
                # 원본 비디오의 가로, 세로 비율 계산
                original_width = clip.w
                original_height = clip.h
                aspect_ratio = original_width / original_height
                
                # 새 너비 계산 (가로세로 비율 유지)
                new_width = int(height * aspect_ratio)
                
                # 직접 resize
                if hasattr(clip, 'resize'):
                    resized_clip = clip.resize(width=new_width, height=height)
                else:
                    # 아예 resize 속성이 없다면 그냥 원본 사용
                    self.root.after(0, lambda: self.log(f"경고: resize 기능을 사용할 수 없어 원본 해상도를 유지합니다."))
                    resized_clip = clip
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"해상도 변경 오류: {err}"))
                resized_clip = clip  # 오류 발생 시 원본 사용
            
            # FPS 설정 (사용자 선택 FPS)
            self.root.after(0, lambda: self.log(f"FPS 변경 중: {clip.fps:.1f}fps -> {fps}fps"))
            
            # FPS 설정
            final_clip = resized_clip.set_fps(fps)
            
            # 진행 상황 업데이트
            self.root.after(0, lambda: self.log(f"인코딩 시작: {output_filename}"))
            
            # 진행 상황 모니터링을 위한 변수
            progress_values = {"value": 0, "last_update": time.time()}
            
            # 진행 상황 모니터링 함수
            def monitor_encoding_progress():
                if os.path.exists(output_path):
                    current_size = os.path.getsize(output_path)
                    # 예상 파일 크기를 계산하기 어려우므로 시간 기반으로 진행률 추정
                    elapsed_time = time.time() - progress_values["last_update"]
                    if elapsed_time > 1:  # 1초마다 업데이트
                        progress_values["value"] += 2  # 임의로 2%씩 증가 (실제 진행과 다를 수 있음)
                        progress_values["value"] = min(progress_values["value"], 99)  # 100%는 완료 시에만
                        progress_values["last_update"] = time.time()
                        self.root.after(0, lambda v=progress_values["value"]: self.file_progress_var.set(v))
                # 계속 모니터링
                if not self.stop_conversion:
                    self.root.after(1000, monitor_encoding_progress)
            
            # 모니터링 시작
            self.root.after(0, monitor_encoding_progress)
            
            # 운영 체제에 따른 인코딩 설정
            if self.system == "Darwin":  # macOS
                # Mac용 최적화된 인코딩 파라미터
                ffmpeg_params = [
                    "-preset", "medium",       # Mac에서는 'fast'보다 'medium'이 안정적
                    "-c:v", "libx264",         # Mac에서는 libx265보다 libx264가 안정적
                    "-profile:v", "high",
                    "-level:v", "4.1",
                    "-b:v", "0.3M",            # 360p에 맞게 조정된 비트레이트
                    "-maxrate", "0.4M",        # 최대 비트레이트
                    "-bufsize", "0.8M",        # 버퍼 크기
                    "-pix_fmt", "yuv420p",
                    "-threads", "0",           # 가용한 모든 쓰레드 사용 (Mac에서 성능 향상)
                    "-movflags", "+faststart"  # 웹 스트리밍 최적화
                ]
            else:  # Windows 또는 Linux
                # Windows/Linux용 H.265 파라미터
                ffmpeg_params = [
                    "-preset", "medium",
                    "-c:v", "libx265",
                    "-tag:v", "hvc1",
                    "-profile:v", "main",
                    "-level:v", "4.1",
                    "-b:v", "0.3M",
                    "-maxrate", "0.4M",
                    "-bufsize", "0.8M",
                    "-pix_fmt", "yuv420p",
                    "-threads", "0",
                    "-movflags", "+faststart"
                ]
            
            # 비디오 변환 및 저장
            try:
                final_clip.write_videofile(
                    output_path,
                    codec='libx264' if self.system == "Darwin" else 'libx265',
                    audio_codec='aac',
                    audio_bitrate='128k',
                    ffmpeg_params=ffmpeg_params,
                    fps=fps,             
                    preset='medium',
                    verbose=False,
                    threads=0,
                    logger=None,
                    temp_audiofile=os.path.join(output_folder, f'temp_audio_{time.time()}.m4a'),
                    write_logfile=False
                )
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"인코딩 오류: {err}"))
                self.root.after(0, lambda: self.log("대안적인 인코딩 방식을 시도합니다..."))
                
                # 첫 번째 방식 실패 시 대체 방식 시도
                try:
                    self.root.after(0, lambda: self.log("기본 설정으로 대체 인코딩 시도 중..."))
                    # 기본 설정으로 변경
                    final_clip.write_videofile(
                        output_path,
                        codec='libx264',  # H.264는 호환성이 높음
                        audio_codec='aac',
                        fps=fps,
                        preset='medium',  # 안정성 위주
                        verbose=False
                    )
                    self.root.after(0, lambda: self.log("기본 설정으로 인코딩 완료"))
                except Exception as e2:
                    self.root.after(0, lambda err=str(e2): self.log(f"대체 인코딩 오류: {err}"))
                    self.root.after(0, lambda: self.log("FFMPEG를 직접 호출하는 방식으로 마지막 시도를 합니다..."))
                    
                    try:
                        # FFMPEG 직접 호출 (마지막 대안)
                        import subprocess
                        
                        # 파일 경로
                        input_path = file_path
                        
                        # 기본 FFMPEG 명령어
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", input_path,
                            "-vf", f"scale=-2:{height}",
                            "-r", str(fps),
                            "-c:v", "libx264",
                            "-preset", "medium",
                            "-crf", "23",
                            "-c:a", "aac",
                            "-b:a", "128k",
                            output_path
                        ]
                        
                        process = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        
                        stdout, stderr = process.communicate()
                        
                        if process.returncode == 0:
                            self.root.after(0, lambda: self.log("FFMPEG 직접 호출로 인코딩 성공"))
                        else:
                            self.root.after(0, lambda: self.log(f"FFMPEG 오류: {stderr}"))
                            return None
                            
                    except Exception as e3:
                        self.root.after(0, lambda err=str(e3): self.log(f"최종 인코딩 오류: {err}"))
                        return None
            
            # 변환 완료 후 정보 업데이트
            converted_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
            original_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
            reduction = (1 - converted_size / original_size) * 100  # 감소율 %
            
            # 메모리 해제
            try:
                final_clip.close()
                resized_clip.close()
                clip.close()
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"메모리 해제 오류: {err} (무시 가능)"))
            
            # 파일 진행 상황 100%로 설정
            self.root.after(0, lambda: self.file_progress_var.set(100))
            
            # 결과 로깅
            self.root.after(0, lambda o=original_size, c=converted_size, r=reduction:
                        self.log(f"변환 결과: {o:.1f} MB → {c:.1f} MB ({r:.1f}% 감소)"))
            
            return output_path
            
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.log(f"변환 오류: {err}"))
            return None


def setup_appearance():
    """운영 체제에 따른 UI 테마 설정"""
    style = ttk.Style()
    system = platform.system()
    
    if system == "Windows":
        # Windows에서는 기본 테마
        pass  # Windows 10/11은 기본 테마가 괜찮음
    elif system == "Darwin":  # macOS
        # Mac에서는 aqua 테마
        style.theme_use('aqua')
    else:  # Linux
        # Linux에서는 clam 테마가 가장 일관적
        try:
            style.theme_use('clam')
        except:
            pass  # 테마가 없으면 기본값 사용


def check_ffmpeg():
    """FFMPEG 설치 확인"""
    try:
        import subprocess
        
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.Popen(
                ["ffmpeg", "-version"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )
        else:
            process = subprocess.Popen(
                ["ffmpeg", "-version"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
        
        stdout, stderr = process.communicate()
        
        if process.returncode == 0:
            # FFMPEG 설치됨
            return True
        else:
            # 설치되지 않음
            return False
    except:
        # 명령어를 찾을 수 없음
        return False


def main():
    """메인 함수"""
    try:
        # tkinter 애플리케이션 시작
        root = tk.Tk()
        
        # 의존성 확인
        check_dependencies()
        
        # UI 테마 설정
        setup_appearance()
        
        # FFMPEG 확인
        if not check_ffmpeg():
            messagebox.showwarning(
                "FFMPEG 확인", 
                "FFMPEG가 시스템에 설치되어 있지 않거나 경로에 추가되지 않았습니다.\n"
                "일부 기능이 제한될 수 있습니다.\n\n"
                "FFMPEG를 설치하고 환경 변수에 추가하는 것을 권장합니다."
            )
        
        # 앱 초기화
        app = MultiFileVideoConverterApp(root)
        
        # 애플리케이션 실행
        root.mainloop()
        
    except Exception as e:
        print(f"애플리케이션 실행 중 오류 발생: {e}")
        
        try:
            # GUI로 오류 표시 시도
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("애플리케이션 오류", str(e))
            root.destroy()
        except:
            # GUI 실패 시 콘솔에 출력
            print(f"오류: {e}")


if __name__ == "__main__":
    main()