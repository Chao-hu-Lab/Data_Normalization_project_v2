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
        master.geometry("1200x850")
        
        # 🎨 優化色彩方案
        self.color_scheme = {
            'background': '#f4f6f9',
            'panel_bg': '#ffffff',
            'primary': '#3498db',
            'success': '#2ecc71',
            'warning': '#f39c12',
            'danger': '#e74c3c',
            'text_dark': '#2c3e50',
            'text_light': '#7f8c8d',
            'running': '#e67e22',
            'border': '#e0e0e0',
            'link': '#0066cc'  # 新增：超連結顏色
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
        
        # 🆕 新增：步驟輸出檔案追蹤
        self.step_outputs = {}  # 格式: {'step_name': 'output_file_path'}
        self.last_output_file = None  # 記錄最後一個輸出檔案
        
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
        
        # 右側：統計面板
        self.create_stats_panel()
        
        # 底部：結果預覽區域
        self.create_result_preview_area()
        
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
        """🎨 配置統一的樣式 - 使用微軟正黑體和Times New Roman"""
        # 主框架
        self.style.configure('Main.TFrame', background=self.color_scheme['background'])
        
        # 步驟框架
        self.style.configure('Step.TFrame', 
                             background=self.color_scheme['panel_bg'], 
                             relief='flat',
                             borderwidth=0)
        
        # 統計面板框架
        self.style.configure('Stats.TFrame',
                             background=self.color_scheme['panel_bg'],
                             relief='flat',
                             borderwidth=0)
        
        # 標題標籤 - 中文使用微軟正黑體
        self.style.configure('Title.TLabel', 
                             font=('Microsoft JhengHei', 18, 'bold'), 
                             foreground=self.color_scheme['text_dark'], 
                             background=self.color_scheme['background'])
        
        # 提示標籤 - 中文使用微軟正黑體
        self.style.configure('Notice.TLabel', 
                             font=('Microsoft JhengHei', 9), 
                             foreground=self.color_scheme['text_light'], 
                             background=self.color_scheme['background'])
        
        # 步驟按鈕
        self.style.configure('Step.TButton', 
                             font=('Microsoft JhengHei', 10, 'bold'),
                             borderwidth=0,
                             relief='flat')
        
        # 統計標籤 - 無底色
        self.style.configure('Stats.TLabel',
                             font=('Microsoft JhengHei', 9),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])
        
        # 統計標題標籤
        self.style.configure('StatsTitle.TLabel',
                             font=('Microsoft JhengHei', 9, 'bold'),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])
        
        # 🆕 新增：超連結按鈕樣式
        self.style.configure('Link.TButton',
                             font=('Microsoft JhengHei', 9, 'underline'),
                             foreground=self.color_scheme['link'],
                             background=self.color_scheme['panel_bg'],
                             borderwidth=0,
                             relief='flat')

    def create_main_layout(self):
        """創建主佈局"""
        self.main_frame = ttk.Frame(self.master, style='Main.TFrame')
        self.main_frame.pack(padx=20, pady=20, fill=tk.BOTH, expand=True)

    def create_header(self):
        """創建標題和控制按鈕"""
        header_frame = ttk.Frame(self.main_frame, style='Main.TFrame')
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 左側：標題
        title_frame = ttk.Frame(header_frame, style='Main.TFrame')
        title_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.title_label = ttk.Label(
            title_frame, 
            text="Data Normalization Workflow v2", 
            style='Title.TLabel'
        )
        self.title_label.pack(anchor='w')
        
        notice_text = (
            "📋 請確保資料已過VBA統一格式 | 四個腳本必須與GUI程式在同一目錄 | "
            "依序執行：ISTD→QC→批次→濃度"
        )
        
        self.notice_label = ttk.Label(
            title_frame, 
            text=notice_text,
            style='Notice.TLabel'
        )
        self.notice_label.pack(anchor='w', pady=(5, 0))
        
        # 右側：控制按鈕
        control_frame = ttk.Frame(header_frame, style='Main.TFrame')
        control_frame.pack(side=tk.RIGHT, padx=(10, 0))
        
        button_width = 12
        
        self.cancel_btn = ttk.Button(
            control_frame,
            text="⏹ 取消執行",
            command=self.cancel_execution,
            state='disabled',
            width=button_width
        )
        self.cancel_btn.pack(pady=2, fill=tk.X)
        
        self.reset_btn = ttk.Button(
            control_frame,
            text="🔄 重置步驟",
            command=self.reset_all_steps,
            width=button_width
        )
        self.reset_btn.pack(pady=2, fill=tk.X)
        
        self.clear_log_btn = ttk.Button(
            control_frame,
            text="🗑 清除日誌",
            command=self.clear_log,
            width=button_width
        )
        self.clear_log_btn.pack(pady=2, fill=tk.X)

    def create_split_layout(self):
        """創建左右分欄佈局"""
        self.split_frame = ttk.Frame(self.main_frame, style='Main.TFrame')
        self.split_frame.pack(fill=tk.BOTH, expand=False, pady=10)
        
        # 左側框架（步驟區域）
        self.left_frame = ttk.Frame(self.split_frame, style='Main.TFrame')
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # 右側框架（統計面板）
        self.right_frame = ttk.Frame(self.split_frame, style='Main.TFrame')
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)

    def create_steps_area(self):
        """創建步驟區域"""
        steps_title = ttk.Label(
            self.left_frame, 
            text="📊 執行步驟",
            font=('Microsoft JhengHei', 12, 'bold'),
            background=self.color_scheme['background'],
            foreground=self.color_scheme['text_dark']
        )
        steps_title.pack(anchor='w', pady=(0, 10))
        
        # 步驟定義
        self.steps = [
            {
                'name': 'Step 1: ISTD 校正',
                'description': '使用內標物進行訊號校正',
                'script': 'ISTD_Correction_v2.py',
                'enabled': True
            },
            {
                'name': 'Step 2: QC 校正',
                'description': '使用品管樣本進行批次間校正',
                'script': 'QC_LOWESS_v2.py',
                'enabled': False
            },
            {
                'name': 'Step 3: 批次效應校正',
                'description': '修正不同批次間的系統性差異',
                'script': 'Batch_Effect_v2.py',
                'enabled': False
            },
            {
                'name': 'Step 4: 濃度校正',
                'description': '將訊號強度藉由校正物轉換為實際濃度',
                'script': 'Concentration_Normalization_v2.py',
                'enabled': False
            }
        ]
        
        self.step_buttons = []
        self.step_status_labels = []
        
        for i, step in enumerate(self.steps):
            step_frame = ttk.Frame(self.left_frame, style='Step.TFrame', relief='solid', borderwidth=1)
            step_frame.pack(fill=tk.X, pady=5, padx=2)
            
            # 內部 padding
            inner_frame = ttk.Frame(step_frame, style='Step.TFrame')
            inner_frame.pack(fill=tk.X, padx=15, pady=12)
            
            # 上排：步驟名稱和狀態
            top_row = ttk.Frame(inner_frame, style='Step.TFrame')
            top_row.pack(fill=tk.X)
            
            step_label = ttk.Label(
                top_row, 
                text=step['name'],
                font=('Microsoft JhengHei', 11, 'bold'),
                background=self.color_scheme['panel_bg'],
                foreground=self.color_scheme['text_dark']
            )
            step_label.pack(side=tk.LEFT)
            
            status_label = ttk.Label(
                top_row,
                text="⚪ 未執行",
                font=('Microsoft JhengHei', 10),
                foreground="gray",
                background=self.color_scheme['panel_bg']
            )
            status_label.pack(side=tk.RIGHT)
            self.step_status_labels.append(status_label)
            
            # 中排：描述
            desc_label = ttk.Label(
                inner_frame,
                text=step['description'],
                font=('Microsoft JhengHei', 9),
                foreground=self.color_scheme['text_light'],
                background=self.color_scheme['panel_bg']
            )
            desc_label.pack(anchor='w', pady=(5, 8))
            
            # 下排：執行按鈕
            btn = ttk.Button(
                inner_frame,
                text="▶ 執行",
                command=lambda s=step: self.execute_step(s),
                style='Step.TButton',
                state='disabled' if not step['enabled'] else 'normal'
            )
            btn.pack(anchor='w')
            self.step_buttons.append(btn)

    def create_stats_panel(self):
        """🆕 優化：創建統計面板，增加超連結功能"""
        # 外框
        stats_container = ttk.Frame(self.right_frame, style='Stats.TFrame', relief='solid', borderwidth=1)
        stats_container.pack(fill=tk.BOTH, expand=True, padx=2)
        
        # 內部 padding
        stats_frame = ttk.Frame(stats_container, style='Stats.TFrame')
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)
        
        # 標題
        title_label = ttk.Label(
            stats_frame,
            text="📈 執行摘要",
            font=('Microsoft JhengHei', 12, 'bold'),
            background=self.color_scheme['panel_bg'],
            foreground=self.color_scheme['text_dark']
        )
        title_label.pack(anchor='w', pady=(0, 15))
        
        # === 當前步驟 ===
        self._create_stats_row(stats_frame, "當前步驟：", "等待執行...")
        self.stats_step_label = self._get_last_value_label(stats_frame)
        
        self._add_separator(stats_frame)
        
        # === 輸入檔案 ===
        self._create_stats_row(stats_frame, "輸入檔案：", "未選擇")
        self.stats_file_label = self._get_last_value_label(stats_frame)
        
        # 🆕 新增：複製檔案路徑按鈕
        copy_input_btn = ttk.Button(
            stats_frame,
            text="📋 複製路徑",
            command=self.copy_input_path,
            width=12
        )
        copy_input_btn.pack(anchor='w', pady=(2, 0))
        self.copy_input_btn = copy_input_btn
        
        self._add_separator(stats_frame)
        
        # === 資料維度 ===
        self._create_stats_row(stats_frame, "資料維度：", "Metabolites: - | Samples: -")
        self.stats_data_label = self._get_last_value_label(stats_frame)
        
        self._add_separator(stats_frame)
        
        # === 🆕 執行時間 ===
        self._create_stats_row(stats_frame, "執行時間：", "未開始")
        self.stats_time_label = self._get_last_value_label(stats_frame)
        
        self._add_separator(stats_frame)
        
        # === 輸出檔案 ===
        self._create_stats_row(stats_frame, "輸出檔案：", "未生成")
        self.stats_output_label = self._get_last_value_label(stats_frame)
        
        # 🆕 新增：輸出檔案操作按鈕（水平排列）
        output_btn_frame = ttk.Frame(stats_frame, style='Stats.TFrame')
        output_btn_frame.pack(anchor='w', pady=(5, 0))
        
        # 打開檔案按鈕
        self.open_file_btn = ttk.Button(
            output_btn_frame,
            text="📄 開啟檔案",
            command=self.open_output_file,
            state='disabled',
            width=12
        )
        self.open_file_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # 打開資料夾按鈕
        self.open_folder_btn = ttk.Button(
            output_btn_frame,
            text="📁 開啟資料夾",
            command=self.open_output_folder,
            state='disabled',
            width=12
        )
        self.open_folder_btn.pack(side=tk.LEFT)
        
        # 🆕 新增：複製輸出路徑按鈕
        copy_output_btn = ttk.Button(
            stats_frame,
            text="📋 複製輸出路徑",
            command=self.copy_output_path,
            state='disabled',
            width=25
        )
        copy_output_btn.pack(anchor='w', pady=(5, 0))
        self.copy_output_btn = copy_output_btn
        
        self._add_separator(stats_frame)
        
        # === 🆕 步驟輸出歷史 ===
        history_label = ttk.Label(
            stats_frame,
            text="📜 步驟輸出記錄：",
            font=('Microsoft JhengHei', 9, 'bold'),
            background=self.color_scheme['panel_bg'],
            foreground=self.color_scheme['text_dark']
        )
        history_label.pack(anchor='w', pady=(10, 5))
        
        # 歷史記錄容器（可滾動）
        history_container = ttk.Frame(stats_frame, style='Stats.TFrame')
        history_container.pack(fill=tk.BOTH, expand=True)
        
        # 創建 Canvas 和 Scrollbar
        canvas = tk.Canvas(
            history_container,
            bg=self.color_scheme['panel_bg'],
            highlightthickness=0,
            height=150
        )
        scrollbar = ttk.Scrollbar(history_container, orient="vertical", command=canvas.yview)
        self.history_frame = ttk.Frame(canvas, style='Stats.TFrame')
        
        self.history_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.history_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.history_canvas = canvas
        
        # 初始化提示
        no_history_label = ttk.Label(
            self.history_frame,
            text="尚無輸出記錄",
            font=('Microsoft JhengHei', 9),
            foreground=self.color_scheme['text_light'],
            background=self.color_scheme['panel_bg']
        )
        no_history_label.pack(pady=10)

    def _create_stats_row(self, parent, title, value):
        """輔助方法：創建統計資訊行"""
        row = ttk.Frame(parent, style='Stats.TFrame')
        row.pack(fill=tk.X, pady=3)
        
        title_label = ttk.Label(
            row,
            text=title,
            style='StatsTitle.TLabel'
        )
        title_label.pack(anchor='w')
        
        value_label = ttk.Label(
            row,
            text=value,
            style='Stats.TLabel',
            wraplength=250
        )
        value_label.pack(anchor='w', padx=(10, 0))

    def _get_last_value_label(self, parent):
        """輔助方法：獲取最後創建的值標籤"""
        for child in parent.winfo_children():
            if isinstance(child, ttk.Frame):
                for subchild in child.winfo_children():
                    if isinstance(subchild, ttk.Label):
                        last_label = subchild
        return last_label

    def _add_separator(self, parent):
        """輔助方法：添加分隔線"""
        sep = ttk.Separator(parent, orient='horizontal')
        sep.pack(fill=tk.X, pady=8)

    def create_result_preview_area(self):
        """創建結果預覽區域"""
        result_frame = ttk.Frame(self.main_frame, style='Main.TFrame')
        result_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        result_title = ttk.Label(
            result_frame,
            text="📋 執行日誌",
            font=('Microsoft JhengHei', 12, 'bold'),
            background=self.color_scheme['background'],
            foreground=self.color_scheme['text_dark']
        )
        result_title.pack(anchor='w', pady=(0, 5))
        
        # 日誌文字區域 - 使用 Times New Roman 顯示英文和數字
        self.result_text = scrolledtext.ScrolledText(
            result_frame,
            height=12,
            wrap=tk.WORD,
            font=('Consolas', 9),
            bg='#2b2b2b',
            fg='#f0f0f0',
            insertbackground='white',
            relief='flat',
            borderwidth=0
        )
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        # 配置標籤顏色
        self.result_text.tag_configure('INFO', foreground='#a8d5ff')
        self.result_text.tag_configure('WARNING', foreground='#ffd966')
        self.result_text.tag_configure('ERROR', foreground='#ff6b6b')
        self.result_text.tag_configure('SUCCESS', foreground='#66ff66')

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
                    # 🆕 記錄輸出檔案
                    self.last_output_file = data['output_path']
                    # 🆕 記錄到步驟輸出
                    if self.current_stats['step_name']:
                        self.step_outputs[self.current_stats['step_name']] = data['output_path']
                    # 🆕 提取輸出資料夾
                    self.current_stats['output_folder'] = os.path.dirname(data['output_path'])
                
                self.update_stats_display()
                
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.check_progress)

    def check_log_queue(self):
        """檢查日誌隊列"""
        try:
            while True:
                record = self.log_queue.get_nowait()
                self.display_log(record)
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.check_log_queue)

    def display_log(self, record):
        """顯示日誌訊息"""
        msg = self.format_log_message(record)
        
        # 根據日誌等級選擇標籤
        if record.levelno >= logging.ERROR:
            tag = 'ERROR'
        elif record.levelno >= logging.WARNING:
            tag = 'WARNING'
        elif '✅' in msg or '成功' in msg:
            tag = 'SUCCESS'
        else:
            tag = 'INFO'
        
        self.result_text.insert(tk.END, msg + '\n', tag)
        self.result_text.see(tk.END)

    def format_log_message(self, record):
        """格式化日誌訊息"""
        return f"{record.getMessage()}"

    def update_stats_display(self):
        """🆕 優化：更新統計顯示，包含按鈕狀態"""
        # 更新步驟名稱
        if self.current_stats['step_name']:
            self.stats_step_label.config(text=self.current_stats['step_name'])
        
        # 更新檔案路徑
        if self.current_stats['file_path']:
            file_name = os.path.basename(self.current_stats['file_path'])
            self.stats_file_label.config(text=file_name)
            self.copy_input_btn.config(state='normal')
        
        # 更新資料維度
        if self.current_stats['metabolites'] > 0 or self.current_stats['samples'] > 0:
            data_text = f"Metabolites: {self.current_stats['metabolites']} | Samples: {self.current_stats['samples']}"
            self.stats_data_label.config(text=data_text)
        
        # 更新輸出檔案
        if self.current_stats['output_path']:
            output_name = os.path.basename(self.current_stats['output_path'])
            self.stats_output_label.config(text=output_name)
            # 🆕 啟用按鈕
            self.open_file_btn.config(state='normal')
            self.open_folder_btn.config(state='normal')
            self.copy_output_btn.config(state='normal')
            
            # 🆕 更新歷史記錄
            self.add_to_history(self.current_stats['step_name'], self.current_stats['output_path'])
        
        # 🆕 更新執行時間
        if self.current_stats['execution_time'] > 0:
            time_text = f"{self.current_stats['execution_time']:.2f} 秒"
            self.stats_time_label.config(text=time_text)
        
        self.master.after(500, self.update_stats_display)

    # 🆕 新增：複製路徑功能
    def copy_input_path(self):
        """複製輸入檔案路徑到剪貼簿"""
        if self.current_stats['file_path']:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.current_stats['file_path'])
            self.logger.info(f"✅ 已複製輸入路徑: {self.current_stats['file_path']}")
            messagebox.showinfo("複製成功", "輸入檔案路徑已複製到剪貼簿")

    def copy_output_path(self):
        """複製輸出檔案路徑到剪貼簿"""
        if self.current_stats['output_path']:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.current_stats['output_path'])
            self.logger.info(f"✅ 已複製輸出路徑: {self.current_stats['output_path']}")
            messagebox.showinfo("複製成功", "輸出檔案路徑已複製到剪貼簿")

    # 🆕 新增：開啟檔案功能
    def open_output_file(self):
        """使用預設程式開啟輸出檔案"""
        if self.current_stats['output_path'] and os.path.exists(self.current_stats['output_path']):
            try:
                if sys.platform == 'win32':
                    os.startfile(self.current_stats['output_path'])
                elif sys.platform == 'darwin':  # macOS
                    subprocess.run(['open', self.current_stats['output_path']])
                else:  # Linux
                    subprocess.run(['xdg-open', self.current_stats['output_path']])
                self.logger.info(f"✅ 已開啟檔案: {self.current_stats['output_path']}")
            except Exception as e:
                self.logger.error(f"❌ 無法開啟檔案: {e}")
                messagebox.showerror("錯誤", f"無法開啟檔案：\n{e}")
        else:
            messagebox.showwarning("警告", "輸出檔案不存在")

    def open_output_folder(self):
        """開啟輸出檔案所在的資料夾"""
        if self.current_stats['output_folder'] and os.path.exists(self.current_stats['output_folder']):
            try:
                if sys.platform == 'win32':
                    # Windows: 開啟資料夾並選中檔案
                    subprocess.run(['explorer', '/select,', self.current_stats['output_path']])
                elif sys.platform == 'darwin':  # macOS
                    subprocess.run(['open', self.current_stats['output_folder']])
                else:  # Linux
                    subprocess.run(['xdg-open', self.current_stats['output_folder']])
                self.logger.info(f"✅ 已開啟資料夾: {self.current_stats['output_folder']}")
            except Exception as e:
                self.logger.error(f"❌ 無法開啟資料夾: {e}")
                messagebox.showerror("錯誤", f"無法開啟資料夾：\n{e}")
        else:
            messagebox.showwarning("警告", "輸出資料夾不存在")

    # 🆕 新增：歷史記錄功能
    def add_to_history(self, step_name, output_path):
        """添加輸出記錄到歷史"""
        # 清除 "尚無輸出記錄" 提示
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        
        # 創建歷史記錄項目
        history_item = ttk.Frame(self.history_frame, style='Stats.TFrame')
        history_item.pack(fill=tk.X, pady=2, padx=5)
        
        # 步驟名稱（縮短顯示）
        step_short = step_name.replace('Step ', 'S').replace(': ', '-')[:20]
        step_label = ttk.Label(
            history_item,
            text=step_short,
            font=('Microsoft JhengHei', 8, 'bold'),
            background=self.color_scheme['panel_bg'],
            foreground=self.color_scheme['text_dark'],
            width=25,
            anchor='w'
        )
        step_label.pack(side=tk.TOP, anchor='w')
        
        # 檔案名稱（可點擊）
        file_name = os.path.basename(output_path)
        file_btn = tk.Label(
            history_item,
            text=f"📄 {file_name[:30]}",
            font=('Microsoft JhengHei', 8, 'underline'),
            fg=self.color_scheme['link'],
            bg=self.color_scheme['panel_bg'],
            cursor='hand2',
            anchor='w'
        )
        file_btn.pack(side=tk.TOP, anchor='w', padx=(5, 0))
        file_btn.bind('<Button-1>', lambda e, path=output_path: self.open_file_from_history(path))
        
        # 更新滾動區域
        self.history_canvas.configure(scrollregion=self.history_canvas.bbox("all"))

    def open_file_from_history(self, file_path):
        """從歷史記錄開啟檔案"""
        if os.path.exists(file_path):
            try:
                if sys.platform == 'win32':
                    os.startfile(file_path)
                elif sys.platform == 'darwin':
                    subprocess.run(['open', file_path])
                else:
                    subprocess.run(['xdg-open', file_path])
                self.logger.info(f"✅ 已從歷史開啟: {file_path}")
            except Exception as e:
                self.logger.error(f"❌ 無法開啟檔案: {e}")
                messagebox.showerror("錯誤", f"無法開啟檔案：\n{e}")
        else:
            messagebox.showwarning("警告", "檔案不存在或已被移動")

    def load_script(self, script_name):
        """動態載入腳本"""
        try:
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name)
            
            if not os.path.exists(script_path):
                self.logger.error(f"腳本不存在: {script_path}")
                return None
            
            spec = importlib.util.spec_from_file_location(script_name, script_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            self.logger.info(f"✅ 成功載入腳本: {script_name}")
            return module
            
        except Exception as e:
            self.logger.error(f"載入腳本失敗: {script_name}")
            self.logger.error(traceback.format_exc())
            return None

    def execute_step(self, step):
        """執行步驟"""
        if self.is_executing:
            messagebox.showwarning("執行中", "已有步驟正在執行，請稍候")
            return
        
        self.logger.info("=" * 80)
        self.logger.info(f"開始執行: {step['name']}")
        self.logger.info("=" * 80)
        
        # 🆕 記錄開始時間
        self.execution_start_time = datetime.now()
        
        # 重置取消標誌
        self.cancel_flag.clear()
        
        # 更新當前步驟名稱
        self.current_stats['step_name'] = step['name']
        self.current_stats['execution_time'] = 0
        
        # 在新線程中執行
        self.current_thread = threading.Thread(
            target=self.run_step,
            args=(step,),
            daemon=True
        )
        self.current_thread.start()
        
        # 更新UI
        self.master.after(0, lambda: self.on_step_start(step))

    def run_step(self, step):
        """在背景線程中執行步驟"""
        try:
            # 🆕 優化：自動選擇上一步驟的輸出檔案
            if step['name'] != 'Step 1: ISTD 校正' and self.last_output_file:
                # 如果不是第一步，且有上一步的輸出，自動使用
                self.logger.info(f"🔄 自動選擇上一步輸出: {os.path.basename(self.last_output_file)}")
                self.selected_file_path = self.last_output_file
                self.file_selected.set()
            else:
                # 第一步或沒有上一步輸出，需要手動選擇
                self.logger.info("請選擇輸入檔案...")
                self.master.after(0, self.select_input_file)
                
                # 等待檔案選擇或取消
                timeout = 300  # 5分鐘超時
                if not self.file_selected.wait(timeout):
                    error_msg = "檔案選擇超時（5分鐘）"
                    self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                    return
                
                # 重置事件
                self.file_selected.clear()
            
            # 檢查是否被取消
            if self.cancel_flag.is_set():
                error_msg = "用戶取消了執行"
                self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                return
            
            # 檢查是否選擇了檔案
            if not self.selected_file_path:
                error_msg = "用戶取消了檔案選擇"
                self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                return
            
            self.logger.info(f"已選擇檔案: {os.path.basename(self.selected_file_path)}")
            
            # 更新統計面板的檔案資訊
            self.current_stats['file_path'] = self.selected_file_path
            self.master.after(0, lambda: self.stats_file_label.config(
                text=os.path.basename(self.selected_file_path)
            ))
            
            # 載入腳本
            script_module = self.load_script(step['script'])
            
            if not script_module:
                raise Exception("腳本載入失敗")
            
            # 🔧 捕獲標準輸出和標準錯誤
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            
            # 使用自定義的StreamToLogger來捕獲輸出
            sys.stdout = StreamToLogger(self.logger, logging.INFO)
            sys.stderr = StreamToLogger(self.logger, logging.ERROR)
            
            try:
                # 執行子程式
                result = script_module.main(input_file=self.selected_file_path)
                
            finally:
                # 恢復標準輸出和標準錯誤
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            
            # 🆕 計算執行時間
            execution_time = (datetime.now() - self.execution_start_time).total_seconds()
            self.current_stats['execution_time'] = execution_time
            
            # 檢查是否被取消
            if self.cancel_flag.is_set():
                error_msg = "執行被用戶取消"
                self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                return
            
            # 🔧 嘗試解析結果並更新統計資訊
            if isinstance(result, dict):
                self.logger.info(f"收到返回結果: {result}")
                self.progress_queue.put(result)
            elif result is None:
                self.logger.warning(f"{step['name']} 返回 None，嘗試從日誌中提取資訊")
            
            # 完成
            self.master.after(0, lambda s=step, r=result: self.on_step_complete(s, r))
            
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"執行失敗: {step['name']}")
            self.logger.error(traceback.format_exc())
            self.master.after(0, lambda s=step, err=error_msg: self.on_step_error(s, err))

    def select_input_file(self):
        """選擇輸入檔案"""
        file_path = filedialog.askopenfilename(
            title="選擇輸入檔案",
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
        """步驟開始時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = True
        
        self.step_status_labels[index].config(
            text="🔄 執行中...", 
            foreground=self.color_scheme['running']
        )
        
        for btn in self.step_buttons:
            btn.config(state='disabled')
        
        self.cancel_btn.config(state='normal')

    def on_step_complete(self, step, result):
        """步驟完成時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = False
        
        self.step_status_labels[index].config(
            text="✅ 已完成", 
            foreground=self.color_scheme['success']
        )
        
        self.completed_steps.add(step['name'])
        
        self.logger.info("=" * 80)
        self.logger.info(f"✅ {step['name']} 執行完成！")
        self.logger.info(f"⏱️ 執行時間: {self.current_stats['execution_time']:.2f} 秒")
        if result and result != True:
            self.logger.info(f"結果: {result}")
        self.logger.info("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')
        
        messagebox.showinfo("完成", f"{step['name']} 已成功執行！\n執行時間: {self.current_stats['execution_time']:.2f} 秒")

    def on_step_error(self, step, error):
        """步驟失敗時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = False
        
        self.step_status_labels[index].config(
            text="❌ 失敗", 
            foreground=self.color_scheme['danger']
        )
        
        self.logger.error("=" * 80)
        self.logger.error(f"❌ {step['name']} 執行失敗！")
        self.logger.error(f"錯誤: {error}")
        self.logger.error("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')
        
        retry = messagebox.askyesno(
            "執行失敗", 
            f"{step['name']} 執行失敗：\n{error}\n\n是否要重試？"
        )
        
        if retry:
            self.execute_step(step)

    def on_step_cancelled(self, step, reason=""):
        """步驟被取消時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = False
        
        self.step_status_labels[index].config(
            text="⚠️ 已取消", 
            foreground=self.color_scheme['warning']
        )
        
        self.logger.warning("=" * 80)
        self.logger.warning(f"⚠️ {step['name']} 執行已取消")
        if reason:
            self.logger.warning(f"原因: {reason}")
        self.logger.warning("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')

    def cancel_execution(self):
        """取消執行"""
        if messagebox.askyesno("確認取消", "確定要取消當前執行嗎？"):
            self.cancel_flag.set()
            self.logger.info("用戶請求取消執行")

    def reset_all_steps(self):
        """重置所有步驟"""
        if self.is_executing:
            messagebox.showwarning("無法重置", "有任務正在執行中，請先取消執行")
            return
        
        if messagebox.askyesno(
            "確認重置", 
            "確定要重置所有步驟嗎？\n這將清除所有完成記錄和輸出歷史。"
        ):
            self.completed_steps.clear()
            self.step_outputs.clear()  # 🆕 清除輸出記錄
            self.last_output_file = None  # 🆕 清除最後輸出
            
            for label in self.step_status_labels:
                label.config(text="⚪ 未執行", foreground="gray")
            
            # 重置統計資訊
            self.current_stats = {
                'step_name': '',
                'file_path': '',
                'metabolites': 0,
                'samples': 0,
                'output_path': '',
                'output_folder': '',
                'execution_time': 0
            }
            
            self.stats_step_label.config(text="等待執行...")
            self.stats_file_label.config(text="未選擇")
            self.stats_data_label.config(text="Metabolites: - | Samples: -")
            self.stats_time_label.config(text="未開始")
            self.stats_output_label.config(text="未生成")
            
            # 🆕 禁用按鈕
            self.open_file_btn.config(state='disabled')
            self.open_folder_btn.config(state='disabled')
            self.copy_input_btn.config(state='disabled')
            self.copy_output_btn.config(state='disabled')
            
            # 🆕 清除歷史記錄
            for widget in self.history_frame.winfo_children():
                widget.destroy()
            
            no_history_label = ttk.Label(
                self.history_frame,
                text="尚無輸出記錄",
                font=('Microsoft JhengHei', 9),
                foreground=self.color_scheme['text_light'],
                background=self.color_scheme['panel_bg']
            )
            no_history_label.pack(pady=10)
            
            self.update_button_states()
            
            self.logger.info("🔄 已重置所有步驟")

    def clear_log(self):
        """清除日誌"""
        if messagebox.askyesno("確認清除", "確定要清除日誌顯示嗎？"):
            self.result_text.delete(1.0, tk.END)
            self.logger.info("清除日誌顯示")


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