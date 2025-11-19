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
import psutil
import re

class DataNormalizationApp:
    def __init__(self, master):
        self.master = master
        master.title("Data Normalization Workflow v2")
        master.geometry("1000x700")
        
        # 🎨 扁平化色彩方案
        self.color_scheme = {
            'background': '#f3f4f6',  # 整體背景色 (淺灰)
            'panel_bg': '#ffffff',    # 區塊背景色 (白)
            'text_dark': '#1f2a37',
            'text_light': '#6b7280',
            'divider': '#e5e7eb',
            'accent': '#4c8bf5',
            'border': '#d1d5db',      # 邊框顏色
            
            # 步驟專屬顏色 (扁平淡色)
            'step1': '#a5b4fc',
            'step2': '#6ee7b7',
            'step3': '#fde68a',
            'step4': '#fca5a5',
            
            'success': '#10b981',
            'running': '#f59e0b',
            'danger': '#ef4444',
            'disabled': '#9ca3af'
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
        self.progress_running = False
        
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
        
        # 🔧 新增：用於從終端機輸出抓取資訊
        self.output_buffer = []
        
        # 設置樣式
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.configure_styles()
        
        # 創建主框架
        self.create_main_layout()
        
        # 創建標題和控制按鈕
        self.create_header()
        
        # 創建左右分欄
        self.create_split_layout()
        
        # 左側：步驟區域
        self.create_steps_area()
        
        # 右側：日誌與資訊面板
        self.create_right_panel()

        # 底部：執行進度區域
        self.create_progress_area()
        
        # 設置日誌系統
        self.setup_logging()
        
        # 開始檢查進度和日誌
        self.check_progress()
        self.check_log_queue()
        self.update_stats_display()
        
        # 初始化按鈕狀態
        self.update_button_states()

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
        """🎨 Configure unified styles - Times New Roman"""
        # Main Frame
        self.style.configure('Main.TFrame', background=self.color_scheme['background'])
        
        # Header Frame (Sky Blue Background)
        self.style.configure('Header.TFrame', 
                             background='#87CEEB',  # Sky Blue
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
        
        # Title Label - Times New Roman, 16pt, Dark text on Sky Blue bg
        self.style.configure('Title.TLabel', 
                             font=('Times New Roman', 16, 'bold'), 
                             foreground=self.color_scheme['text_dark'], 
                             background='#87CEEB')
        
        # Notice Label - Times New Roman, 10pt, Dark text on Sky Blue bg
        self.style.configure('Notice.TLabel', 
                             font=('Times New Roman', 12), 
                             foreground=self.color_scheme['text_dark'], 
                             background='#87CEEB')
        
        # Step Button
        self.style.configure('Step.TButton', 
                             font=('Times New Roman', 12, 'bold'),
                             borderwidth=0,
                             relief='flat')
        
        # Compact Step Frame
        self.style.configure('CompactStep.TFrame',
                             background=self.color_scheme['panel_bg'],
                             relief='flat')

        # Stats Label - No background
        self.style.configure('Stats.TLabel',
                             font=('Times New Roman', 12),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])
        
        # Stats Title Label
        self.style.configure('StatsTitle.TLabel',
                             font=('Times New Roman', 12, 'bold'),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])

    def create_main_layout(self):
        """Create main layout"""
        self.main_frame = ttk.Frame(self.master, style='Main.TFrame')
        self.main_frame.pack(padx=20, pady=20, fill=tk.BOTH, expand=True)

    def create_header(self):
        """Create header and control buttons"""
        # Use Header.TFrame for blue background
        header_frame = ttk.Frame(self.main_frame, style='Header.TFrame', padding=12)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Left: Title
        title_frame = ttk.Frame(header_frame, style='Header.TFrame')
        title_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.title_label = ttk.Label(
            title_frame, 
            text="Data Normalization Workflow v2", 
            style='Title.TLabel'
        )
        self.title_label.pack(anchor='w')
        
        notice_text = (
            "Ensure data is VBA-formatted | Scripts must be in same dir | "
            "Order: ISTD -> QC -> Batch -> Conc."
        )
        
        self.notice_label = ttk.Label(
            title_frame, 
            text=notice_text,
            style='Notice.TLabel'
        )
        self.notice_label.pack(anchor='w', pady=(5, 0))
        
        # Right: Control Buttons
        control_frame = ttk.Frame(header_frame, style='Header.TFrame')
        control_frame.pack(side=tk.RIGHT, padx=(12, 0))
        
        button_width = 12
        
        self.cancel_btn = ttk.Button(
            control_frame,
            text="⏹ Stop",
            command=self.cancel_execution,
            state='disabled',
            width=button_width
        )
        self.cancel_btn.pack(pady=2, fill=tk.X)
        
        self.reset_btn = ttk.Button(
            control_frame,
            text="🔄 Reset",
            command=self.reset_all_steps,
            width=button_width
        )
        self.reset_btn.pack(pady=2, fill=tk.X)
        
        self.clear_log_btn = ttk.Button(
            control_frame,
            text="🗑 Clear Log",
            command=self.clear_log,
            width=button_width
        )
        self.clear_log_btn.pack(pady=2, fill=tk.X)

    def create_split_layout(self):
        """創建左右分欄佈局"""
        self.split_frame = ttk.Frame(self.main_frame, style='Main.TFrame')
        self.split_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 左側框架（步驟區域）- 使用 Panel.TFrame 增加邊框和背景
        self.left_frame = ttk.Frame(self.split_frame, style='Panel.TFrame', padding=15)
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))
        
        # 右側框架（統計面板）- 使用 Panel.TFrame 增加邊框和背景
        self.right_frame = ttk.Frame(self.split_frame, style='Panel.TFrame', padding=15)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    def create_steps_area(self):
        """Create steps area (Compact)"""
        # === Input File Area ===
        input_frame = ttk.Frame(self.left_frame, style='Main.TFrame')
        input_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            input_frame, 
            text="📂 Input File:",
            font=('Times New Roman', 12, 'bold'),
            background=self.color_scheme['background']
        ).pack(anchor='w')
        
        file_select_frame = ttk.Frame(input_frame, style='Main.TFrame')
        file_select_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.input_file_label = ttk.Label(
            file_select_frame,
            text="No file selected...",
            font=('Times New Roman', 12),
            background='white',
            relief='solid',
            borderwidth=1,
            padding=5,
            width=30
        )
        self.input_file_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(
            file_select_frame,
            text="Select",
            command=self.select_initial_file,
            width=8
        ).pack(side=tk.LEFT)

        # === Steps List ===
        steps_title_frame = ttk.Frame(self.left_frame, style='Main.TFrame')
        steps_title_frame.pack(fill=tk.X, pady=(10, 5))
        
        ttk.Label(
            steps_title_frame, 
            text="🛠️ Workflow Steps",
            font=('Times New Roman', 12, 'bold'),
            background=self.color_scheme['background']
        ).pack(side=tk.LEFT)
        
        # Auto Run Button
        self.run_all_btn = ttk.Button(
            steps_title_frame,
            text="⚡ Auto Run",
            command=self.run_all_steps,
            state='disabled'
        )
        self.run_all_btn.pack(side=tk.RIGHT)
        
        # Step Definitions
        self.steps = [
            {'name': 'Step 1: ISTD Correction', 'script': 'ISTD_Correction_v2.py', 'enabled': True, 'color': self.color_scheme['step1']},
            {'name': 'Step 2: QC Correction', 'script': 'QC_LOWESS_v2.py', 'enabled': False, 'color': self.color_scheme['step2']},
            {'name': 'Step 3: Batch Correction', 'script': 'Batch_Effect_v2.py', 'enabled': False, 'color': self.color_scheme['step3']},
            {'name': 'Step 4: Conc. Normalization', 'script': 'Concentration_Normalization_v2.py', 'enabled': False, 'color': self.color_scheme['step4']}
        ]
        
        self.step_buttons = []
        self.step_status_labels = []
        self.step_excel_buttons = []
        self.step_plot_buttons = []
        
        # List Container
        list_container = ttk.Frame(self.left_frame, style='Step.TFrame')
        list_container.pack(fill=tk.BOTH, expand=True)
        
        # Wrapper for centering steps vertically
        steps_wrapper = tk.Frame(list_container, bg=self.color_scheme['panel_bg'])
        steps_wrapper.pack(expand=True, fill=tk.X)
        
        for i, step in enumerate(self.steps):
            row_frame = tk.Frame(steps_wrapper, bg=self.color_scheme['panel_bg'])
            row_frame.pack(fill=tk.X, pady=6)

            # 左側顏色條
            color_bar = tk.Frame(row_frame, bg=step['color'], width=6)
            color_bar.pack(side=tk.LEFT, fill=tk.Y)

            # Step 標籤區（與左側顏色條連接，形成 L 型）
            step_label_container = tk.Frame(row_frame, bg=step['color'])
            step_label_container.pack(side=tk.LEFT, fill=tk.Y)
            
            step_label = tk.Label(
                step_label_container, 
                text=step['name'].split(':')[0], # Step X
                font=('Times New Roman', 10, 'bold'),
                fg='black',
                bg=step['color'],
                width=8,
                anchor='center',
                padx=5,
                pady=8
            )
            step_label.pack(fill=tk.BOTH, expand=True)
            
            # 右側內容區
            inner = tk.Frame(row_frame, bg=self.color_scheme['panel_bg'], padx=10, pady=8)
            inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # Left Info Area
            left_info = tk.Frame(inner, bg=self.color_scheme['panel_bg'])
            left_info.pack(side=tk.LEFT, fill=tk.X)
            
            tk.Label(
                left_info,
                text=step['name'].split(':')[1], # Name
                font=('Times New Roman', 12),
                bg=self.color_scheme['panel_bg']
            ).pack(side=tk.LEFT, padx=5)
            
            # Right Control Area
            right_control = tk.Frame(inner, bg=self.color_scheme['panel_bg'], padx=5)
            right_control.pack(side=tk.RIGHT)
            
            # Status
            status_label = tk.Label(
                right_control,
                text="⚪",
                font=('Times New Roman', 12),
                bg=self.color_scheme['panel_bg'],
                width=3
            )
            status_label.pack(side=tk.LEFT, padx=5)
            self.step_status_labels.append(status_label)
            
            # Run Button (四周邊框)
            btn = tk.Button(
                right_control,
                text="▶",
                command=lambda s=step: self.execute_step(s),
                font=('Times New Roman', 12, 'bold'),
                bg=self.color_scheme['background'],
                relief='solid',
                borderwidth=1,
                width=4,
                state='disabled' if not step['enabled'] else 'normal'
            )
            btn.pack(side=tk.LEFT, padx=2)
            self.step_buttons.append(btn)
            
            # Excel Button (四周邊框)
            excel_btn = tk.Button(
                right_control,
                text="📑",
                command=lambda s=step: self.open_step_excel(s),
                font=('Times New Roman', 12),
                bg=self.color_scheme['background'],
                relief='solid',
                borderwidth=1,
                width=4,
                state='disabled'
            )
            excel_btn.pack(side=tk.LEFT, padx=2)
            self.step_excel_buttons.append(excel_btn)
            
            # Plot Button (四周邊框)
            plot_btn = tk.Button(
                right_control,
                text="     🖼️",
                command=lambda s=step: self.open_step_plots(s),
                font=('Times New Roman', 12),
                bg=self.color_scheme['background'],
                relief='solid',
                borderwidth=1,
                width=4,
                state='disabled'
            )
            plot_btn.pack(side=tk.LEFT, padx=2)
            self.step_plot_buttons.append(plot_btn)

    def create_right_panel(self):
        """Create right panel (Log & Info)"""
        right_container = ttk.Frame(self.right_frame, style='Main.TFrame')
        right_container.pack(fill=tk.BOTH, expand=True)

        info_frame = tk.Frame(right_container, bg=self.color_scheme['panel_bg'])
        info_frame.pack(fill=tk.X, pady=(0, 12))
        inner_info = tk.Frame(info_frame, bg=self.color_scheme['panel_bg'], padx=16, pady=14)
        inner_info.pack(fill=tk.X)
        
        # Title
        ttk.Label(
            inner_info,
            text="📊 Status",
            font=('Times New Roman', 12, 'bold'),
            background=self.color_scheme['panel_bg']
        ).pack(anchor='w', pady=(0, 8))
        
        # Info Grid
        grid_frame = tk.Frame(inner_info, bg=self.color_scheme['panel_bg'])
        grid_frame.pack(fill=tk.X)
        
        self.stats_step_label = ttk.Label(grid_frame, text="Current Step: Idle", style='Stats.TLabel')
        self.stats_step_label.grid(row=0, column=0, sticky='w', pady=(0, 4))

        # Data Dimensions
        self.stats_data_label = ttk.Label(grid_frame, text="Data Matrix: -", style='Stats.TLabel')
        self.stats_data_label.grid(row=1, column=0, sticky='w')

        # === Log Area ===
        log_frame = ttk.Frame(right_container, style='Main.TFrame')
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(
            log_frame,
            text="📋 Execution Log",
            font=('Times New Roman', 12, 'bold'),
            background=self.color_scheme['background']
        ).pack(anchor='w', pady=(0, 5))
        
        self.result_text = scrolledtext.ScrolledText(
            log_frame,
            height=10,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg='#2b2b2b',
            fg='#f0f0f0',
            insertbackground='white',
            relief='flat',
            borderwidth=0
        )
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure Tag Colors
        self.result_text.tag_configure('INFO', foreground='#a8d5ff')
        self.result_text.tag_configure('WARNING', foreground='#ffd966')
        self.result_text.tag_configure('ERROR', foreground='#ff6b6b')
        self.result_text.tag_configure('SUCCESS', foreground='#66ff66')

    def create_progress_area(self):
        """Create bottom progress area"""
        self.progress_frame = ttk.Frame(self.main_frame, style='Main.TFrame')
        self.progress_frame.pack(fill=tk.X, pady=(5, 0))

        # Use Panel.TFrame for border and background
        progress_inner = ttk.Frame(self.progress_frame, style='Panel.TFrame', padding=10)
        progress_inner.pack(fill=tk.X)

        content = ttk.Frame(progress_inner, style='Stats.TFrame')
        content.pack(fill=tk.X)

        ttk.Label(
            content,
            text="Progress",
            style='StatsTitle.TLabel'
        ).pack(anchor='w')

        self.progress_label = ttk.Label(
            content,
            text="Not started",
            style='Stats.TLabel'
        )
        self.progress_label.pack(anchor='w', pady=(2, 6))

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
            
            # 雖然是 determinate 模式，但如果需要顯示"正在跑"的感覺，可以保留 running 參數做其他用途
            # 但這裡主要依賴 value 來顯示進度
            pass

    def update_button_states(self):
        """更新按鈕狀態"""
        # Step 1 永遠可用
        self.step_buttons[0].config(state='normal')
        
        # 其他步驟需要前一步驟完成
        for i in range(1, len(self.steps)):
            prev_step = self.steps[i-1]['name']
            if prev_step in self.completed_steps:
                self.step_buttons[i].config(state='normal')
            else:
                self.step_buttons[i].config(state='disabled')

    def check_progress(self):
        """檢查進度隊列"""
        try:
            while True:
                data = self.progress_queue.get_nowait()
                
                # 更新統計資訊
                if 'metabolites' in data:
                    self.current_stats['metabolites'] = data['metabolites']
                if 'samples' in data:
                    self.current_stats['samples'] = data['samples']
                if 'output_path' in data:
                    self.current_stats['output_path'] = data['output_path']
                    self.last_output_file = data['output_path']
                    # 記錄到步驟輸出 (用於開啟資料夾)
                    if self.current_stats['step_name']:
                        self.step_outputs[self.current_stats['step_name']] = data['output_path']
                
                self.update_stats_display()
                
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.check_progress)

    def update_stats_display(self):
        """更新統計顯示"""
        # 更新步驟
        if self.current_stats['step_name']:
            self.stats_step_label.config(text=f"Current Step: {self.current_stats['step_name']}")
        
        # 更新資料維度
        if self.current_stats['metabolites'] > 0:
            self.stats_data_label.config(
                text=f"Data Matrix: {self.current_stats['metabolites']} Metabolites | {self.current_stats['samples']} Samples"
            )
        
        self.master.after(100, self.update_stats_display)

    def open_step_excel(self, step):
        """Open step output Excel file"""
        step_name = step['name']
        if step_name in self.step_outputs:
            path = self.step_outputs[step_name]
            if os.path.exists(path):
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
        # Infer plot folder from step name
        base_plot_dir = ""
        if "ISTD" in step_name:
            base_plot_dir = "ISTD_Correction_plots"
        elif "QC" in step_name:
            base_plot_dir = "QC_LOWESS_plots"
        elif "Batch" in step_name:
            base_plot_dir = "Batch_Effect_plots"
        elif "Conc" in step_name:
            base_plot_dir = "Normalization_Figures"
            
        if not base_plot_dir:
            return

        # Try to find corresponding output folder
        # Logic: If there is an output Excel, try to find the Plot folder from the Excel filename or timestamp
        # Simplified logic: Open the main folder of that category, let the user choose the latest one
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', base_plot_dir)
        
        # If there is a specific output file, try to find a folder with the same name (usually the script creates a folder with the same name)
        if step_name in self.step_outputs:
            excel_path = self.step_outputs[step_name]
            excel_name = os.path.splitext(os.path.basename(excel_path))[0]
            specific_plot_dir = os.path.join(output_dir, excel_name)
            if os.path.exists(specific_plot_dir):
                output_dir = specific_plot_dir
        
        if os.path.exists(output_dir):
            try:
                if sys.platform == 'win32':
                    os.startfile(output_dir)
                elif sys.platform == 'darwin':
                    subprocess.run(['open', output_dir])
                else:
                    subprocess.run(['xdg-open', output_dir])
            except Exception as e:
                self.logger.error(f"Cannot open folder: {e}")
        else:
            messagebox.showwarning("Warning", f"Plot folder not found: {base_plot_dir}")

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


    def load_script(self, script_name):
        """Dynamically load script"""
        try:
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name)
            
            if not os.path.exists(script_path):
                self.logger.error(f"Script not found: {script_path}")
                return None
            
            spec = importlib.util.spec_from_file_location(script_name, script_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            self.logger.info(f"✅ Successfully loaded script: {script_name}")
            return module
            
        except Exception as e:
            self.logger.error(f"Failed to load script: {script_name}")
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
            self.input_file_label.config(text=os.path.basename(file_path))
            self.logger.info(f"Selected initial file: {file_path}")
            # Enable auto run
            self.run_all_btn.config(state='normal')

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
            path = self.step_outputs[step_name]
            folder = os.path.dirname(path)
            if os.path.exists(folder):
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
            
            # Load script
            script_module = self.load_script(step['script'])
            
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
            if isinstance(result, dict):
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
            fg=self.color_scheme['warning']
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
                
            self.input_file_label.config(text="No file selected...")
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
            
            self.stats_step_label.config(text="Current Step: Idle")
            self.stats_data_label.config(text="Data: -")
            
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