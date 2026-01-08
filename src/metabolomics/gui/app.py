import tkinter as tk
from tkinter import messagebox, ttk, scrolledtext, filedialog
import importlib.util
import os
import sys
import traceback
import threading
import queue
import logging
from datetime import datetime
import subprocess
from metabolomics.utils.results import ProcessingResult


# ========== Platform-Aware Font Settings ==========
def get_system_fonts():
    """Return platform-appropriate fonts for cross-platform compatibility"""
    if sys.platform == 'darwin':  # macOS
        return {
            'sans': 'Helvetica',
            'mono': 'Monaco'
        }
    else:  # Windows/Linux
        return {
            'sans': 'Arial',
            'mono': 'Consolas'
        }

FONTS = get_system_fonts()


class DataNormalizationApp:
    def __init__(self, master):
        self.master = master
        master.title("Data Normalization Workflow v2")
        master.geometry("1150x900")
        master.minsize(1000, 750)  # 設定最小視窗大小，確保進度條不被遮擋
        
        # 🎨 現代化色彩方案
        self.color_scheme = {
            'background': '#f0f2f5',      # 整體背景色 (淺灰)
            'panel_bg': '#ffffff',        # 區塊背景色 (白)
            'hero_bg': '#1a73e8',         # Hero Section 背景 (主色調藍)
            'hero_text': '#ffffff',       # Hero Section 文字
            'text_dark': '#1f2a37',
            'text_light': '#6b7280',
            'divider': '#e5e7eb',
            'accent': '#1a73e8',          # 主色調
            'accent_hover': '#1557b0',    # 主色調懸停
            'border': '#d1d5db',          # 邊框顏色
            'card_shadow': '#00000015',   # 卡片陰影
            
            # 步驟專屬顏色 (扁平淡色)
            'step1': '#e8f0fe',
            'step1_accent': '#1a73e8',
            'step2': '#e6f4ea',
            'step2_accent': '#34a853',
            'step3': '#fef7e0',
            'step3_accent': '#f9ab00',
            'step4': '#fce8e6',
            'step4_accent': '#ea4335',
            
            'success': '#34a853',
            'running': '#f9ab00',
            'danger': '#ea4335',
            'disabled': '#9ca3af',
            'ghost': '#e8eaed',            # Ghost 按鈕背景
            'ghost_text': '#5f6368',       # Ghost 按鈕文字
            'primary': '#1a73e8',          # 主要按鈕
            'primary_text': '#ffffff'      # 主要按鈕文字
        }
        
        master.configure(bg=self.color_scheme['background'])

        # 執行狀態管理
        self.completed_steps = set()
        self.current_thread = None
        self.cancel_flag = threading.Event()
        self.progress_queue = queue.Queue()
        self.is_executing = False
        self.log_queue = queue.Queue()
        
        # 檔案選擇相關
        self.file_selected = threading.Event()
        self.selected_file_path = None
        
        self.last_output_file = None  # 記錄最後一個輸出檔案
        self.step_outputs = {}
        self.auto_run_mode = False
        self.current_step_index = -1  # 追蹤當前步驟索引
        
        # 統計資訊
        self.current_stats = {
            'step_name': '',
            'file_path': '',
            'metabolites': 0,
            'samples': 0,
            'output_path': '',
            'output_folder': '',  # 🆕 新增：輸出資料夾路徑
            'execution_time': 0  # 🆕 新增：執行時間
        }

        # 設置樣式
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.configure_styles()
        
        # 創建主框架
        self.create_main_layout()
        
        # 底部：執行進度區域 (先 pack 到底部，確保不被遮擋)
        self.create_progress_area()
        
        # 創建頂部標題區
        self.create_title_section()
        
        # 創建頂部 Hero Section (檔案選擇)
        self.create_hero_section()
        
        # 創建標題和控制按鈕
        self.create_header()
        
        # 創建左右分欄
        self.create_split_layout()
        
        # 左側：步驟區域 (卡片式)
        self.create_steps_area()
        
        # 右側：分頁式資訊面板 (Stats + Log)
        self.create_right_panel()
        
        # 設置日誌系統
        self.setup_logging()
        
        # 開始檢查進度和日誌
        self.check_progress()
        self.check_log_queue()
        self.update_stats_display()
        
        # 初始化按鈕狀態
        self.update_button_states()

    # ========== UI 輔助方法 ==========

    def _create_status_card(self, parent, icon, title, initial_value, value_color=None):
        """建立統計狀態卡片

        Parameters:
        -----------
        parent : tk.Frame
            父容器
        icon : str
            圖示 emoji
        title : str
            卡片標題
        initial_value : str
            初始顯示值
        value_color : str, optional
            數值顏色，預設使用 text_dark

        Returns:
        --------
        tk.Label : 可更新的數值標籤
        """
        card = tk.Frame(parent, bg='#f8f9fa', padx=16, pady=12)
        card.pack(fill=tk.X, pady=(0, 12))

        tk.Label(
            card,
            text=f"{icon} {title}",
            font=(FONTS['sans'], 10),
            fg=self.color_scheme['text_light'],
            bg='#f8f9fa'
        ).pack(anchor='w')

        value_label = tk.Label(
            card,
            text=initial_value,
            font=(FONTS['sans'], 14, 'bold'),
            fg=value_color or self.color_scheme['text_dark'],
            bg='#f8f9fa'
        )
        value_label.pack(anchor='w', pady=(4, 0))

        return value_label

    def _create_ghost_button(self, parent, text, command, emoji=None, width=None):
        """建立 Ghost 樣式按鈕

        Parameters:
        -----------
        parent : tk.Frame
            父容器
        text : str
            按鈕文字
        command : callable
            點擊回調
        emoji : str, optional
            前綴 emoji
        width : int, optional
            按鈕寬度

        Returns:
        --------
        tk.Button : 建立的按鈕
        """
        display_text = f"{emoji} {text}" if emoji else text
        btn = tk.Button(
            parent,
            text=display_text,
            command=command,
            font=(FONTS['sans'], 9),
            bg=self.color_scheme['ghost'],
            fg=self.color_scheme['ghost_text'],
            relief='flat',
            padx=8,
            pady=2
        )
        if width:
            btn.config(width=width)
        return btn

    def _result_to_dict(self, result):
        if isinstance(result, ProcessingResult):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return None

    def _get_output_path(self, result):
        if isinstance(result, ProcessingResult):
            return result.output_path
        if isinstance(result, dict):
            return result.get('output_path')
        if isinstance(result, str):
            return result
        return None

    def _get_plots_dir(self, result):
        if isinstance(result, ProcessingResult):
            return result.plots_dir
        if isinstance(result, dict):
            return result.get('plots_dir')
        return None

    def setup_logging(self):
        """設置日誌系統"""
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(
            log_dir, 
            f'normalization_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        )
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        gui_handler = QueueHandler(self.log_queue)
        gui_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(gui_handler)
        
        self.logger.info("=" * 80)
        self.logger.info("Data Normalization Workflow v2 啟動")
        self.logger.info("=" * 80)

    def configure_styles(self):
        """🎨 Configure unified styles - Arial (Modern)"""
        # Main Frame
        self.style.configure('Main.TFrame', background=self.color_scheme['background'])
        
        # Header Frame (控制按鈕區域)
        self.style.configure('Header.TFrame', 
                             background=self.color_scheme['background'],
                             relief='flat')
        
        # Hero Frame (檔案選擇區域 - 主色調)
        self.style.configure('Hero.TFrame', 
                             background=self.color_scheme['hero_bg'],
                             relief='flat')
        
        # Panel Frame (with border)
        self.style.configure('Panel.TFrame', 
                             background=self.color_scheme['panel_bg'], 
                             relief='solid',
                             borderwidth=1,
                             bordercolor=self.color_scheme['border'])
        
        # Step Frame
        self.style.configure('Step.TFrame', 
                             background=self.color_scheme['panel_bg'], 
                             relief='flat',
                             borderwidth=0)
        
        # Stats Panel Frame
        self.style.configure('Stats.TFrame',
                             background=self.color_scheme['panel_bg'],
                             relief='flat',
                             borderwidth=0)
        
        # Card Frame (卡片式設計)
        self.style.configure('Card.TFrame',
                             background=self.color_scheme['panel_bg'],
                             relief='flat',
                             borderwidth=0)
        
        # Title Label - Arial, 18pt, White text on Hero bg
        self.style.configure('HeroTitle.TLabel', 
                             font=(FONTS['sans'], 18, 'bold'), 
                             foreground=self.color_scheme['hero_text'], 
                             background=self.color_scheme['hero_bg'])
        
        # Hero Subtitle
        self.style.configure('HeroSubtitle.TLabel', 
                             font=(FONTS['sans'], 11), 
                             foreground='#cce0ff', 
                             background=self.color_scheme['hero_bg'])
        
        # Section Title Label - Arial, 14pt
        self.style.configure('Title.TLabel', 
                             font=(FONTS['sans'], 14, 'bold'), 
                             foreground=self.color_scheme['text_dark'], 
                             background=self.color_scheme['background'])
        
        # Notice Label - Arial, 10pt
        self.style.configure('Notice.TLabel', 
                             font=(FONTS['sans'], 10), 
                             foreground=self.color_scheme['text_light'], 
                             background=self.color_scheme['background'])
        
        # Step Button
        self.style.configure('Step.TButton', 
                             font=(FONTS['sans'], 11, 'bold'),
                             borderwidth=0,
                             relief='flat')
        
        # Primary Button Style
        self.style.configure('Primary.TButton',
                             font=(FONTS['sans'], 11, 'bold'),
                             background=self.color_scheme['primary'],
                             foreground=self.color_scheme['primary_text'])
        
        # Ghost Button Style
        self.style.configure('Ghost.TButton',
                             font=(FONTS['sans'], 11),
                             background=self.color_scheme['ghost'],
                             foreground=self.color_scheme['ghost_text'])
        
        # Compact Step Frame
        self.style.configure('CompactStep.TFrame',
                             background=self.color_scheme['panel_bg'],
                             relief='flat')

        # Stats Label - No background
        self.style.configure('Stats.TLabel',
                             font=(FONTS['sans'], 11),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])
        
        # Stats Title Label
        self.style.configure('StatsTitle.TLabel',
                             font=(FONTS['sans'], 12, 'bold'),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])
        
        # Tab Style
        self.style.configure('TNotebook', background=self.color_scheme['panel_bg'])
        self.style.configure('TNotebook.Tab', 
                             font=(FONTS['sans'], 11),
                             padding=[12, 6])

    def create_main_layout(self):
        """Create main layout - 使用 grid 佈局確保進度條不被遮擋"""
        # 主容器使用 grid 佈局
        self.master.grid_rowconfigure(0, weight=1)
        self.master.grid_columnconfigure(0, weight=1)

        self.main_frame = ttk.Frame(self.master, style='Main.TFrame')
        self.main_frame.grid(row=0, column=0, padx=20, pady=15, sticky='nsew')

        # 主框架內部也使用 grid 佈局
        self.main_frame.grid_rowconfigure(4, weight=1)  # split_frame 行可擴展
        self.main_frame.grid_columnconfigure(0, weight=1)

    def create_title_section(self):
        """Create title section - 頂部標題區"""
        # 標題容器 - 使用 grid row 0
        title_container = tk.Frame(self.main_frame, bg=self.color_scheme['background'])
        title_container.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        
        # 主標題
        main_title = tk.Label(
            title_container,
            text="Data Normalization Workflow v2",
            font=(FONTS['sans'], 20, 'bold'),
            fg=self.color_scheme['text_dark'],
            bg=self.color_scheme['background']
        )
        main_title.pack(anchor='w')
        
        # 副標題說明
        subtitle = tk.Label(
            title_container,
            text="Metabolomics data processing pipeline | VBA-formatted Excel required",
            font=(FONTS['sans'], 11),
            fg=self.color_scheme['text_light'],
            bg=self.color_scheme['background']
        )
        subtitle.pack(anchor='w', pady=(2, 0))
        
        # 分隔線 - 使用 grid row 1
        separator = tk.Frame(self.main_frame, bg=self.color_scheme['divider'], height=1)
        separator.grid(row=1, column=0, sticky='ew', pady=(5, 15))

    def create_hero_section(self):
        """Create Hero Section - 檔案選擇區域 (頂部橫幅)"""
        # Hero 容器 - 主色調背景 - 使用 grid row 2
        hero_container = tk.Frame(self.main_frame, bg=self.color_scheme['hero_bg'])
        hero_container.grid(row=2, column=0, sticky='ew', pady=(0, 15))
        
        hero_inner = tk.Frame(hero_container, bg=self.color_scheme['hero_bg'], padx=24, pady=20)
        hero_inner.pack(fill=tk.X)
        
        # 左側：標題與說明
        left_section = tk.Frame(hero_inner, bg=self.color_scheme['hero_bg'])
        left_section.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        title_label = tk.Label(
            left_section,
            text="📂 Input File Selection",
            font=(FONTS['sans'], 16, 'bold'),
            fg=self.color_scheme['hero_text'],
            bg=self.color_scheme['hero_bg']
        )
        title_label.pack(anchor='w')
        
        subtitle_label = tk.Label(
            left_section,
            text="Select your VBA-formatted Excel file to begin the workflow",
            font=(FONTS['sans'], 11),
            fg='#cce0ff',
            bg=self.color_scheme['hero_bg']
        )
        subtitle_label.pack(anchor='w', pady=(4, 0))
        
        # 右側：檔案選擇區
        right_section = tk.Frame(hero_inner, bg=self.color_scheme['hero_bg'])
        right_section.pack(side=tk.RIGHT)
        
        # 檔案顯示框
        file_display_frame = tk.Frame(right_section, bg='#ffffff', padx=2, pady=2)
        file_display_frame.pack(side=tk.LEFT, padx=(0, 10))
        
        self.input_file_label = tk.Label(
            file_display_frame,
            text="  No file selected...  ",
            font=(FONTS['sans'], 11),
            bg='#ffffff',
            fg=self.color_scheme['text_light'],
            width=35,
            anchor='w',
            padx=10,
            pady=8
        )
        self.input_file_label.pack()
        
        # 選擇按鈕 (白色背景)
        select_btn = tk.Button(
            right_section,
            text="📁 Browse...",
            command=self.select_initial_file,
            font=(FONTS['sans'], 11, 'bold'),
            bg='#ffffff',
            fg=self.color_scheme['hero_bg'],
            activebackground='#f0f0f0',
            relief='flat',
            padx=20,
            pady=8,
            cursor='hand2'
        )
        select_btn.pack(side=tk.LEFT)

    def create_header(self):
        """Create header and control buttons"""
        # 使用 grid row 3
        header_frame = ttk.Frame(self.main_frame, style='Header.TFrame')
        header_frame.grid(row=3, column=0, sticky='ew', pady=(0, 10))
        
        # Left: Title & Notice
        title_frame = ttk.Frame(header_frame, style='Header.TFrame')
        title_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.title_label = tk.Label(
            title_frame, 
            text="🛠️ Workflow Steps", 
            font=(FONTS['sans'], 14, 'bold'),
            fg=self.color_scheme['text_dark'],
            bg=self.color_scheme['background']
        )
        self.title_label.pack(anchor='w')
        
        notice_text = "Order: ISTD → QC → Batch → Conc. | Scripts must be in same directory"
        
        self.notice_label = tk.Label(
            title_frame, 
            text=notice_text,
            font=(FONTS['sans'], 10),
            fg=self.color_scheme['text_light'],
            bg=self.color_scheme['background']
        )
        self.notice_label.pack(anchor='w', pady=(2, 0))
        
        # Right: Control Buttons
        control_frame = tk.Frame(header_frame, bg=self.color_scheme['background'])
        control_frame.pack(side=tk.RIGHT, padx=(12, 0))
        
        # Auto Run Button
        self.run_all_btn = tk.Button(
            control_frame,
            text="⚡ Auto Run",
            command=self.run_all_steps,
            font=(FONTS['sans'], 10, 'bold'),
            bg=self.color_scheme['primary'],
            fg=self.color_scheme['primary_text'],
            activebackground=self.color_scheme['accent_hover'],
            relief='flat',
            padx=12,
            pady=4,
            state='disabled',
            cursor='hand2'
        )
        self.run_all_btn.pack(side=tk.LEFT, padx=3)
        
        self.cancel_btn = tk.Button(
            control_frame,
            text="⏹ Stop",
            command=self.cancel_execution,
            font=(FONTS['sans'], 10),
            bg=self.color_scheme['ghost'],
            fg=self.color_scheme['ghost_text'],
            relief='flat',
            padx=12,
            pady=4,
            state='disabled'
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=3)
        
        self.reset_btn = tk.Button(
            control_frame,
            text="🔄 Reset",
            command=self.reset_all_steps,
            font=(FONTS['sans'], 10),
            bg=self.color_scheme['ghost'],
            fg=self.color_scheme['ghost_text'],
            relief='flat',
            padx=12,
            pady=4
        )
        self.reset_btn.pack(side=tk.LEFT, padx=3)

    def create_split_layout(self):
        """創建左右分欄佈局 - 使用 grid row 4"""
        # 使用 PanedWindow 確保左右等高
        self.split_frame = tk.PanedWindow(
            self.main_frame,
            orient=tk.HORIZONTAL,
            bg=self.color_scheme['background'],
            sashwidth=8,
            sashrelief='flat'
        )
        self.split_frame.grid(row=4, column=0, sticky='nsew', pady=5)
        
        # 左側框架（步驟區域）- 卡片式設計
        self.left_frame = tk.Frame(self.split_frame, bg=self.color_scheme['background'])
        self.split_frame.add(self.left_frame, minsize=400, stretch='always')
        
        # 右側框架（分頁式資訊面板）
        self.right_frame = tk.Frame(
            self.split_frame, 
            bg=self.color_scheme['panel_bg'],
            highlightbackground=self.color_scheme['border'],
            highlightthickness=1
        )
        self.split_frame.add(self.right_frame, minsize=350, stretch='always')

    def create_steps_area(self):
        """Create steps area - Card Layout with Input Source Display"""
        # Step Definitions
        self.steps = [
            {'name': 'Step 1: ISTD Correction', 'module': 'metabolomics.processors.istd', 'enabled': True,
             'color': self.color_scheme['step1'], 'accent': self.color_scheme['step1_accent']},
            {'name': 'Step 2: QC Correction', 'module': 'metabolomics.processors.qc_lowess', 'enabled': False,
             'color': self.color_scheme['step2'], 'accent': self.color_scheme['step2_accent']},
            {'name': 'Step 3: Batch Correction', 'module': 'metabolomics.processors.batch_effect', 'enabled': False,
             'color': self.color_scheme['step3'], 'accent': self.color_scheme['step3_accent']},
            {'name': 'Step 4: Conc. Normalization', 'module': 'metabolomics.processors.normalization', 'enabled': False,
             'color': self.color_scheme['step4'], 'accent': self.color_scheme['step4_accent']}
        ]

        self.step_buttons = []
        self.step_status_labels = []
        self.step_excel_buttons = []
        self.step_plot_buttons = []
        self.step_input_labels = []  # 新增：輸入來源標籤
        self.step_cards = []  # 新增：卡片容器

        # 簡單的卡片容器（不需要滾動）
        cards_container = tk.Frame(self.left_frame, bg=self.color_scheme['background'])
        cards_container.pack(fill=tk.BOTH, expand=True)
        
        for i, step in enumerate(self.steps):
            # === 卡片容器 ===
            card_frame = tk.Frame(
                cards_container, 
                bg=self.color_scheme['panel_bg'],
                highlightbackground=self.color_scheme['border'],
                highlightthickness=1,
                padx=0,
                pady=0
            )
            card_frame.pack(fill=tk.X, pady=8, ipady=4)  # 增加卡片間距和內部高度 (1.25x)
            self.step_cards.append(card_frame)
            
            # 卡片內部佈局
            card_inner = tk.Frame(card_frame, bg=self.color_scheme['panel_bg'])
            card_inner.pack(fill=tk.X, padx=0, pady=0)
            
            # === 左側：顏色指示條 + 步驟編號 ===
            left_indicator = tk.Frame(card_inner, bg=step['accent'], width=50)
            left_indicator.pack(side=tk.LEFT, fill=tk.Y)
            left_indicator.pack_propagate(False)
            
            step_num_label = tk.Label(
                left_indicator,
                text=f"Step\n{i+1}",
                font=(FONTS['sans'], 11, 'bold'),
                fg='#ffffff',
                bg=step['accent'],
                justify='center'
            )
            step_num_label.pack(expand=True)
            
            # === 中間：步驟資訊區 ===
            info_section = tk.Frame(card_inner, bg=self.color_scheme['panel_bg'], padx=15, pady=15)  # pady: 12 -> 15 (1.25x)
            info_section.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # 步驟名稱
            step_name_label = tk.Label(
                info_section,
                text=step['name'].split(':')[1].strip(),
                font=(FONTS['sans'], 13, 'bold'),
                fg=self.color_scheme['text_dark'],
                bg=self.color_scheme['panel_bg'],
                anchor='w'
            )
            step_name_label.pack(anchor='w')
            
            # 輸入來源顯示 (Chain of Custody)
            input_source_frame = tk.Frame(info_section, bg=self.color_scheme['panel_bg'])
            input_source_frame.pack(anchor='w', pady=(4, 0))
            
            input_icon_label = tk.Label(
                input_source_frame,
                text="📥 Input: ",
                font=(FONTS['sans'], 10),
                fg=self.color_scheme['text_light'],
                bg=self.color_scheme['panel_bg']
            )
            input_icon_label.pack(side=tk.LEFT)
            
            # 根據步驟索引顯示不同的輸入來源
            if i == 0:
                input_text = "Waiting for file selection..."
            else:
                input_text = f"← Output from Step {i}"
            
            input_source_label = tk.Label(
                input_source_frame,
                text=input_text,
                font=(FONTS['sans'], 10),
                fg=step['accent'],
                bg=self.color_scheme['panel_bg']
            )
            input_source_label.pack(side=tk.LEFT)
            self.step_input_labels.append(input_source_label)
            
            # === 右側：控制按鈕區 ===
            control_section = tk.Frame(card_inner, bg=self.color_scheme['panel_bg'], padx=15, pady=15)  # pady: 12 -> 15 (1.25x)
            control_section.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 按鈕行
            btn_row = tk.Frame(control_section, bg=self.color_scheme['panel_bg'])
            btn_row.pack()
            
            # 狀態指示器
            status_label = tk.Label(
                btn_row,
                text="⚪",
                font=(FONTS['sans'], 14),
                bg=self.color_scheme['panel_bg'],
                width=2
            )
            status_label.pack(side=tk.LEFT, padx=(0, 8))
            self.step_status_labels.append(status_label)
            
            # 執行按鈕 (Primary/Ghost 樣式)
            is_first_step = (i == 0)
            btn_bg = self.color_scheme['ghost'] if not is_first_step else step['accent']
            btn_fg = self.color_scheme['ghost_text'] if not is_first_step else '#ffffff'
            
            run_btn = tk.Button(
                btn_row,
                text="▶ Run",
                command=lambda s=step: self.execute_step(s),
                font=(FONTS['sans'], 10, 'bold'),
                bg=btn_bg,
                fg=btn_fg,
                activebackground=step['accent'],
                relief='flat',
                padx=12,
                pady=4,
                width=6,
                state='disabled' if not step['enabled'] else 'normal',
                cursor='hand2'
            )
            run_btn.pack(side=tk.LEFT, padx=2)
            self.step_buttons.append(run_btn)
            
            # Excel 按鈕
            excel_btn = tk.Button(
                btn_row,
                text="📑",
                command=lambda s=step: self.open_step_excel(s),
                font=(FONTS['sans'], 11),
                bg=self.color_scheme['ghost'],
                fg=self.color_scheme['ghost_text'],
                relief='flat',
                padx=8,
                pady=4,
                state='disabled'
            )
            excel_btn.pack(side=tk.LEFT, padx=2)
            self.step_excel_buttons.append(excel_btn)
            
            # Plot 按鈕
            plot_btn = tk.Button(
                btn_row,
                text="📊",
                command=lambda s=step: self.open_step_plots(s),
                font=(FONTS['sans'], 11),
                bg=self.color_scheme['ghost'],
                fg=self.color_scheme['ghost_text'],
                relief='flat',
                padx=8,
                pady=4,
                state='disabled'
            )
            plot_btn.pack(side=tk.LEFT, padx=2)
            self.step_plot_buttons.append(plot_btn)

    def create_right_panel(self):
        """Create right panel - Tabbed Interface (Stats + Log)"""
        # 建立 Notebook (分頁容器)
        self.info_notebook = ttk.Notebook(self.right_frame)
        self.info_notebook.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        # === Tab 1: 執行日誌 ===
        log_tab = tk.Frame(self.info_notebook, bg=self.color_scheme['panel_bg'])
        self.info_notebook.add(log_tab, text="📋 Execution Log")
        
        # Log 標題列
        log_header = tk.Frame(log_tab, bg=self.color_scheme['panel_bg'])
        log_header.pack(fill=tk.X, padx=12, pady=(12, 6))
        
        tk.Label(
            log_header,
            text="Real-time execution output",
            font=(FONTS['sans'], 10),
            fg=self.color_scheme['text_light'],
            bg=self.color_scheme['panel_bg']
        ).pack(side=tk.LEFT)
        
        # Clear Log Button (使用輔助方法)
        clear_log_btn = self._create_ghost_button(
            log_header, "Clear", self.clear_log, emoji="🗑"
        )
        clear_log_btn.pack(side=tk.RIGHT)
        
        # Log 文字區域
        log_container = tk.Frame(log_tab, bg=self.color_scheme['panel_bg'])
        log_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        
        self.result_text = scrolledtext.ScrolledText(
            log_container,
            wrap=tk.WORD,
            font=(FONTS['mono'], 10),
            bg='#1e1e1e',
            fg='#d4d4d4',
            insertbackground='white',
            relief='flat',
            borderwidth=0
        )
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure Tag Colors
        self.result_text.tag_configure('INFO', foreground='#9cdcfe')
        self.result_text.tag_configure('WARNING', foreground='#dcdcaa')
        self.result_text.tag_configure('ERROR', foreground='#f14c4c')
        self.result_text.tag_configure('SUCCESS', foreground='#4ec9b0')
        
        # === Tab 2: 狀態統計 ===
        stats_tab = tk.Frame(self.info_notebook, bg=self.color_scheme['panel_bg'])
        self.info_notebook.add(stats_tab, text="📊 Status")

        stats_inner = tk.Frame(stats_tab, bg=self.color_scheme['panel_bg'], padx=20, pady=20)
        stats_inner.pack(fill=tk.BOTH, expand=True)

        # 使用輔助方法建立狀態卡片
        self.stats_step_label = self._create_status_card(
            stats_inner, "🔄", "Current Step", "Idle"
        )
        self.stats_data_label = self._create_status_card(
            stats_inner, "📐", "Data Matrix", "No data loaded"
        )
        self.stats_completed_label = self._create_status_card(
            stats_inner, "✅", "Completed Steps", "0 / 4",
            value_color=self.color_scheme['success']
        )

    def create_progress_area(self):
        """Create bottom progress area - 使用 grid row 5 確保不被遮擋"""
        # 進度條固定在底部 - 使用 grid row 5
        self.progress_frame = tk.Frame(self.main_frame, bg=self.color_scheme['background'])
        self.progress_frame.grid(row=5, column=0, sticky='sew', pady=(10, 0))

        # 進度條容器
        progress_inner = tk.Frame(
            self.progress_frame, 
            bg=self.color_scheme['panel_bg'],
            highlightbackground=self.color_scheme['border'],
            highlightthickness=1
        )
        progress_inner.pack(fill=tk.X)

        content = tk.Frame(progress_inner, bg=self.color_scheme['panel_bg'], padx=16, pady=12)
        content.pack(fill=tk.X)

        # 進度標題與文字
        progress_header = tk.Frame(content, bg=self.color_scheme['panel_bg'])
        progress_header.pack(fill=tk.X, pady=(0, 8))
        
        tk.Label(
            progress_header,
            text="⏳ Progress",
            font=(FONTS['sans'], 11, 'bold'),
            fg=self.color_scheme['text_dark'],
            bg=self.color_scheme['panel_bg']
        ).pack(side=tk.LEFT)

        self.progress_label = tk.Label(
            progress_header,
            text="Not started",
            font=(FONTS['sans'], 11),
            fg=self.color_scheme['text_light'],
            bg=self.color_scheme['panel_bg']
        )
        self.progress_label.pack(side=tk.RIGHT)

        # 進度條
        self.progress_bar = ttk.Progressbar(
            content,
            mode='determinate',
            maximum=100,
            length=400
        )
        self.progress_bar.pack(fill=tk.X)

        self.set_progress("Not started", value=0, running=False)

    def set_progress(self, text, value=None, running=False):
        """更新進度條顯示與狀態"""
        if hasattr(self, 'progress_label'):
            self.progress_label.config(text=text)
        if hasattr(self, 'progress_bar'):
            if value is not None:
                self.progress_bar['value'] = value

    def update_button_states(self):
        """更新按鈕狀態 - 引導式按鈕樣式"""
        # 找出下一個應該執行的步驟
        next_step_index = 0
        for i, step in enumerate(self.steps):
            if step['name'] not in self.completed_steps:
                next_step_index = i
                break
            next_step_index = len(self.steps)  # 全部完成
        
        # Step 1 永遠可用
        self.step_buttons[0].config(state='normal')
        
        # 更新所有按鈕樣式
        for i in range(len(self.steps)):
            step = self.steps[i]
            prev_step = self.steps[i-1]['name'] if i > 0 else None
            
            # 判斷是否可以執行此步驟
            can_execute = (i == 0) or (prev_step and prev_step in self.completed_steps)
            
            if can_execute:
                self.step_buttons[i].config(state='normal')
                
                # 如果是下一個待執行步驟 (Primary 高亮樣式)
                if step['name'] not in self.completed_steps and i == next_step_index:
                    self.step_buttons[i].config(
                        bg=step['accent'],
                        fg='#ffffff',
                        font=(FONTS['sans'], 10, 'bold')
                    )
                    # 更新卡片邊框高亮
                    if hasattr(self, 'step_cards') and i < len(self.step_cards):
                        self.step_cards[i].config(highlightbackground=step['accent'], highlightthickness=2)
                else:
                    # 已完成步驟 (Ghost 樣式)
                    self.step_buttons[i].config(
                        bg=self.color_scheme['ghost'],
                        fg=self.color_scheme['ghost_text'],
                        font=(FONTS['sans'], 10)
                    )
                    if hasattr(self, 'step_cards') and i < len(self.step_cards):
                        self.step_cards[i].config(highlightbackground=self.color_scheme['border'], highlightthickness=1)
            else:
                # 未解鎖步驟 (Disabled 樣式)
                self.step_buttons[i].config(
                    state='disabled',
                    bg=self.color_scheme['ghost'],
                    fg=self.color_scheme['disabled'],
                    font=(FONTS['sans'], 10)
                )
                if hasattr(self, 'step_cards') and i < len(self.step_cards):
                    self.step_cards[i].config(highlightbackground=self.color_scheme['border'], highlightthickness=1)
        
        # 更新完成進度標籤
        if hasattr(self, 'stats_completed_label'):
            completed_count = len(self.completed_steps)
            self.stats_completed_label.config(text=f"{completed_count} / 4")

    def check_progress(self):
        """檢查進度隊列"""
        try:
            while True:
                data = self.progress_queue.get_nowait()
                data_dict = self._result_to_dict(data)
                if not data_dict:
                    continue
                
                # 更新統計資訊
                if 'metabolites' in data_dict:
                    self.current_stats['metabolites'] = data_dict['metabolites']
                if 'samples' in data_dict:
                    self.current_stats['samples'] = data_dict['samples']
                if 'output_path' in data_dict:
                    self.current_stats['output_path'] = data_dict['output_path']
                    self.last_output_file = data_dict['output_path']
                    # 記錄到步驟輸出 (用於開啟資料夾)
                    if self.current_stats['step_name']:
                        if isinstance(data, ProcessingResult):
                            self.step_outputs[self.current_stats['step_name']] = data
                        else:
                            self.step_outputs[self.current_stats['step_name']] = data_dict
                
                self.update_stats_display()
                
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.check_progress)

    def update_stats_display(self):
        """更新統計顯示"""
        # 更新步驟
        if self.current_stats['step_name']:
            self.stats_step_label.config(text=self.current_stats['step_name'])
        else:
            self.stats_step_label.config(text="Idle")
        
        # 更新資料維度
        if self.current_stats['metabolites'] > 0:
            self.stats_data_label.config(
                text=f"{self.current_stats['metabolites']} Metabolites × {self.current_stats['samples']} Samples"
            )
        else:
            self.stats_data_label.config(text="No data loaded")
        
        # 更新完成進度
        if hasattr(self, 'stats_completed_label'):
            completed_count = len(self.completed_steps)
            self.stats_completed_label.config(text=f"{completed_count} / 4")
        
        self.master.after(100, self.update_stats_display)
    
    def update_input_source_labels(self):
        """更新輸入來源顯示 (Chain of Custody)"""
        if not hasattr(self, 'step_input_labels'):
            return
            
        for i, label in enumerate(self.step_input_labels):
            if i == 0:
                # Step 1: 顯示使用者選取的原始檔案
                if self.selected_file_path:
                    filename = os.path.basename(self.selected_file_path)
                    label.config(text=filename, fg=self.steps[0]['accent'])
                else:
                    label.config(text="Waiting for file selection...", fg=self.color_scheme['text_light'])
            else:
                # Step 2~4: 顯示上一步驟的輸出檔案
                prev_step_name = self.steps[i-1]['name']
                if prev_step_name in self.step_outputs:
                    output_path = self._get_output_path(self.step_outputs[prev_step_name])
                    if output_path:
                        output_filename = os.path.basename(output_path)
                        label.config(text=f"← {output_filename}", fg=self.steps[i]['accent'])
                    else:
                        label.config(text=f"← Output from Step {i}", fg=self.color_scheme['text_light'])
                else:
                    label.config(text=f"← Output from Step {i}", fg=self.color_scheme['text_light'])

    def open_step_excel(self, step):
        """Open step output Excel file"""
        step_name = step['name']
        if step_name in self.step_outputs:
            path = self._get_output_path(self.step_outputs[step_name])
            if path and os.path.exists(path):
                try:
                    if sys.platform == 'win32':
                        os.startfile(path)
                    elif sys.platform == 'darwin':
                        subprocess.run(['open', path])
                    else:
                        subprocess.run(['xdg-open', path])
                except Exception as e:
                    self.logger.error(f"Cannot open file: {e}")
            else:
                messagebox.showwarning("Warning", "File does not exist")
        else:
            messagebox.showwarning("Notice", "No output generated for this step yet")

    def open_step_plots(self, step):
        """Open step output plots folder"""
        step_name = step['name']
        if step_name in self.step_outputs:
            plots_dir = self._get_plots_dir(self.step_outputs[step_name])
            if plots_dir and os.path.exists(plots_dir):
                try:
                    if sys.platform == 'win32':
                        os.startfile(plots_dir)
                    elif sys.platform == 'darwin':
                        subprocess.run(['open', plots_dir])
                    else:
                        subprocess.run(['xdg-open', plots_dir])
                except Exception as e:
                    self.logger.error(f"Cannot open folder: {e}")
            else:
                messagebox.showwarning("Warning", "Plot folder does not exist")
        else:
            messagebox.showwarning("Notice", "No plots generated for this step yet")

    def check_log_queue(self):
        """Check log queue"""
        try:
            while True:
                record = self.log_queue.get_nowait()
                self.display_log(record)
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.check_log_queue)

    def display_log(self, record):
        """Display log message"""
        msg = self.format_log_message(record)
        
        # Choose tag based on log level
        if record.levelno >= logging.ERROR:
            tag = 'ERROR'
        elif record.levelno >= logging.WARNING:
            tag = 'WARNING'
        elif '✅' in msg or 'Success' in msg or 'Completed' in msg:
            tag = 'SUCCESS'
        else:
            tag = 'INFO'
        
        self.result_text.insert(tk.END, msg + '\n', tag)
        self.result_text.see(tk.END)

    def format_log_message(self, record):
        """Format log message"""
        return f"{record.getMessage()}"


    def load_script(self, module_name):
        """Dynamically load processor module"""
        try:
            import importlib
            module = importlib.import_module(module_name)

            self.logger.info(f"Successfully loaded module: {module_name}")
            return module

        except Exception as e:
            self.logger.error(f"Failed to load module: {module_name}")
            self.logger.error(traceback.format_exc())
            return None

    def select_initial_file(self):
        """Select initial input file"""
        file_path = filedialog.askopenfilename(
            title="Select Input File",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if file_path:
            self.selected_file_path = file_path
            filename = os.path.basename(file_path)
            self.input_file_label.config(
                text=f"  {filename}  ",
                fg=self.color_scheme['text_dark']
            )
            self.logger.info(f"Selected initial file: {file_path}")
            # Enable auto run
            self.run_all_btn.config(state='normal')
            # 更新輸入來源標籤
            self.update_input_source_labels()
            # 更新按鈕狀態
            self.update_button_states()

    def run_all_steps(self):
        """Run all steps automatically"""
        if not self.selected_file_path:
            messagebox.showwarning("Notice", "Please select an input file first")
            return
        
        if self.is_executing:
            return

        if messagebox.askyesno("Confirm", "Are you sure you want to run all steps automatically?"):
            self.auto_run_mode = True
            self.execute_step(self.steps[0])

    def open_step_folder(self, step):
        """Open step output folder"""
        step_name = step['name']
        if step_name in self.step_outputs:
            path = self._get_output_path(self.step_outputs[step_name])
            folder = os.path.dirname(path) if path else None
            if folder and os.path.exists(folder):
                try:
                    if sys.platform == 'win32':
                        os.startfile(folder)
                    elif sys.platform == 'darwin':
                        subprocess.run(['open', folder])
                    else:
                        subprocess.run(['xdg-open', folder])
                except Exception as e:
                    self.logger.error(f"Cannot open folder: {e}")
            else:
                messagebox.showwarning("Warning", "Folder does not exist")
        else:
            messagebox.showwarning("Notice", "No output generated for this step yet")

    def execute_step(self, step):
        """Execute step"""
        if self.is_executing:
            messagebox.showwarning("Running", "A step is already running, please wait")
            return
        
        self.logger.info("=" * 80)
        self.logger.info(f"Starting: {step['name']}")
        self.logger.info("=" * 80)
        
        # 🆕 Record start time
        self.execution_start_time = datetime.now()
        
        # Reset cancel flag
        self.cancel_flag.clear()
        
        # Update current step name
        self.current_stats['step_name'] = step['name']
        self.current_stats['execution_time'] = 0
        
        # Run in new thread
        self.current_thread = threading.Thread(
            target=self.run_step,
            args=(step,),
            daemon=True
        )
        self.current_thread.start()
        
        # Update UI
        self.master.after(0, lambda: self.on_step_start(step))

    def run_step(self, step):
        """Run step in background thread"""
        try:
            current_input = None
            
            if step['name'] == 'Step 1: ISTD Correction':
                if not self.selected_file_path:
                    error_msg = "Please select an input file first"
                    self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                    return
                current_input = self.selected_file_path
            else:
                if self.last_output_file:
                    current_input = self.last_output_file
                    self.logger.info(f"🔄 Auto-selected previous output: {os.path.basename(current_input)}")
                else:
                    error_msg = "Previous output not found. Please ensure previous step succeeded."
                    self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                    return
            
            self.logger.info(f"Using input file: {os.path.basename(current_input)}")
            
            # Load processor module
            script_module = self.load_script(step['module'])
            
            if not script_module:
                raise Exception("Failed to load script")
            
            # 🔧 Capture stdout and stderr
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            
            # Use custom StreamToLogger
            sys.stdout = StreamToLogger(self.logger, logging.INFO)
            sys.stderr = StreamToLogger(self.logger, logging.ERROR)
            
            try:
                # Execute subprocess
                result = script_module.main(input_file=current_input)
                
            finally:
                # Restore stdout and stderr
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            
            # 🆕 Calculate execution time
            execution_time = (datetime.now() - self.execution_start_time).total_seconds()
            self.current_stats['execution_time'] = execution_time
            
            # Check if cancelled
            if self.cancel_flag.is_set():
                error_msg = "Execution cancelled by user"
                self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                return
            
            # 🔧 Try to parse result and update stats
            if isinstance(result, ProcessingResult):
                self.logger.info(f"Received result: {result.to_dict()}")
                self.progress_queue.put(result)
            elif isinstance(result, dict):
                self.logger.info(f"Received result: {result}")
                self.progress_queue.put(result)
            elif result is None:
                self.logger.warning(f"{step['name']} returned None, trying to extract info from logs")
            
            # Complete
            self.master.after(0, lambda s=step, r=result: self.on_step_complete(s, r))
            
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Execution failed: {step['name']}")
            self.logger.error(traceback.format_exc())
            self.master.after(0, lambda s=step, err=error_msg: self.on_step_error(s, err))

    def select_input_file(self):
        """Select input file"""
        file_path = filedialog.askopenfilename(
            title="Select Input File",
            filetypes=[
                ("Excel files", "*.xlsx *.xls"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            self.selected_file_path = file_path
            self.file_selected.set()
        else:
            self.selected_file_path = None
            self.file_selected.set()

    def on_step_start(self, step):
        """UI update on step start"""
        index = self.steps.index(step)
        
        self.is_executing = True
        
        self.step_status_labels[index].config(
            text="🔄", 
            fg=self.color_scheme['running']
        )
        
        for btn in self.step_buttons:
            btn.config(state='disabled')
        
        self.cancel_btn.config(state='normal')
        
        # Set start progress
        start_progress = index * 25
        self.set_progress(f"{step['name']} Running...", value=start_progress, running=True)

    def on_step_complete(self, step, result):
        """UI update on step complete"""
        index = self.steps.index(step)
        
        self.is_executing = False
        
        self.step_status_labels[index].config(
            text="✅", 
            fg=self.color_scheme['success']
        )
        
        # Enable buttons
        self.step_excel_buttons[index].config(state='normal')
        self.step_plot_buttons[index].config(state='normal')
        
        self.completed_steps.add(step['name'])
        
        self.logger.info("=" * 80)
        self.logger.info(f"✅ {step['name']} Completed!")
        self.logger.info(f"⏱️ Execution Time: {self.current_stats['execution_time']:.2f} s")
        if result and result != True:
            self.logger.info(f"Result: {result}")
        self.logger.info("=" * 80)
        
        # 更新輸入來源標籤 (Chain of Custody)
        self.update_input_source_labels()
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')
        
        # Set end progress
        end_progress = (index + 1) * 25
        self.set_progress(f"{step['name']} Completed", value=end_progress, running=False)
        
        # Auto run logic
        if self.auto_run_mode:
            next_index = index + 1
            if next_index < len(self.steps):
                self.logger.info(f"⏳ Auto-running next step in 1s: {self.steps[next_index]['name']}")
                self.master.after(1000, lambda: self.execute_step(self.steps[next_index]))
            else:
                self.auto_run_mode = False
                messagebox.showinfo("Auto Run Complete", "All steps completed!")
        else:
            messagebox.showinfo("Complete", f"{step['name']} Successfully Executed!\nTime: {self.current_stats['execution_time']:.2f} s")
        
        # Ensure progress bar shows completion
        self.set_progress(f"{step['name']} Completed", value=end_progress, running=False)

    def on_step_error(self, step, error):
        """UI update on step error"""
        index = self.steps.index(step)
        
        self.is_executing = False
        self.auto_run_mode = False # Stop auto run
        
        self.step_status_labels[index].config(
            text="❌", 
            fg=self.color_scheme['danger']
        )
        
        self.logger.error("=" * 80)
        self.logger.error(f"❌ {step['name']} Failed!")
        self.logger.error(f"Error: {error}")
        self.logger.error("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')
        
        self.set_progress(f"{step['name']} Error", running=False)
        
        retry = messagebox.askyesno(
            "Execution Failed", 
            f"{step['name']} Failed:\n{error}\n\nRetry?"
        )
        
        if retry:
            self.execute_step(step)

    def on_step_cancelled(self, step, reason=""):
        """UI update on step cancelled"""
        index = self.steps.index(step)
        
        self.is_executing = False
        self.auto_run_mode = False # Stop auto run
        
        self.step_status_labels[index].config(
            text="⚠️", 
            fg=self.color_scheme['running']
        )
        
        self.logger.warning("=" * 80)
        self.logger.warning(f"⚠️ {step['name']} Cancelled")
        if reason:
            self.logger.warning(f"Reason: {reason}")
        self.logger.warning("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')
        self.set_progress(f"{step['name']} Cancelled", running=False)

    def cancel_execution(self):
        """Cancel execution"""
        if messagebox.askyesno("Confirm Cancel", "Are you sure you want to cancel?"):
            self.cancel_flag.set()
            self.auto_run_mode = False
            self.logger.info("User requested cancellation")

    def reset_all_steps(self):
        """Reset all steps"""
        if self.is_executing:
            messagebox.showwarning("Cannot Reset", "Task is running, please cancel first")
            return
        
        if messagebox.askyesno(
            "Confirm Reset", 
            "Are you sure you want to reset all steps?"
        ):
            self.completed_steps.clear()
            self.step_outputs.clear()
            self.last_output_file = None
            self.auto_run_mode = False
            
            # Reset UI
            for label in self.step_status_labels:
                label.config(text="⚪", fg="gray")
            
            for btn in self.step_excel_buttons:
                btn.config(state='disabled')
            for btn in self.step_plot_buttons:
                btn.config(state='disabled')
            
            # Reset file selection
            self.input_file_label.config(
                text="  No file selected...  ",
                fg=self.color_scheme['text_light']
            )
            self.selected_file_path = None
            self.run_all_btn.config(state='disabled')
            
            # Reset stats
            self.current_stats = {
                'step_name': '',
                'file_path': '',
                'metabolites': 0,
                'samples': 0,
                'output_path': '',
                'output_folder': '',
                'execution_time': 0
            }
            
            self.stats_step_label.config(text="Idle")
            self.stats_data_label.config(text="No data loaded")
            if hasattr(self, 'stats_completed_label'):
                self.stats_completed_label.config(text="0 / 4")
            
            # 更新輸入來源標籤
            self.update_input_source_labels()
            
            self.update_button_states()
            
            self.logger.info("🔄 All steps reset")
            self.set_progress("Not started", value=0, running=False)

    def clear_log(self):
        """Clear log"""
        if messagebox.askyesno("Confirm Clear", "Clear log display?"):
            self.result_text.delete(1.0, tk.END)
            self.logger.info("Log display cleared")


# 自定義日誌處理器類
class QueueHandler(logging.Handler):
    """將日誌發送到隊列的處理器"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    
    def emit(self, record):
        self.log_queue.put(record)


# 自定義輸出流類
class StreamToLogger:
    """將標準輸出重定向到日誌系統"""
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''
    
    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())
    
    def flush(self):
        pass


def main():
    root = tk.Tk()
    app = DataNormalizationApp(root)
    
    def on_closing():
        if app.is_executing:
            if messagebox.askokcancel("退出", "有任務正在執行，確定要退出嗎？\n這將強制終止當前任務。"):
                app.cancel_flag.set()
                app.logger.info("程式關閉，強制終止執行")
                root.destroy()
        else:
            app.logger.info("程式正常關閉")
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
