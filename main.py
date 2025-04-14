import sys
import asyncio
import json
import cv2
import websockets
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel,
    QSlider, QFileDialog, QGridLayout, QHBoxLayout, QStyle,
    QGroupBox, QFrame, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize, QTimer, QRectF, QDateTime
from PyQt5.QtGui import QImage, QPixmap, QIcon, QPainter, QColor, QFont, QPalette
from qasync import QEventLoop
from ultralytics import YOLO


class CircularProgress(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 120)  # Larger size for better visibility
        self.battery_percentage = 0
        self.setStyleSheet("background: transparent;")

    def set_battery_percentage(self, percentage):
        """Set the battery percentage and update the display."""
        self.battery_percentage = percentage
        self.update()

    def paintEvent(self, event):
        """Custom paint event to draw the circular progress bar."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(10, 10, 100, 100)  # Circle size
        
        # Determine color based on battery level
        if self.battery_percentage > 60:
            color = QColor(0, 200, 0)  # Green
        elif self.battery_percentage > 30:
            color = QColor(255, 165, 0)  # Orange
        else:
            color = QColor(220, 0, 0)  # Red
        
        # Draw the circle background (gray)
        painter.setPen(QColor(100, 100, 100))
        painter.setBrush(QColor(50, 50, 50))
        painter.drawEllipse(rect)
        
        # Draw the circle foreground (battery status)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        start_angle = 90 * 16  # Start from the top of the circle (in 1/16th degrees)
        span_angle = int(-(self.battery_percentage * 360) * 16 / 100)  # Convert to integer
        painter.drawPie(rect, start_angle, span_angle)
        
        # Draw the percentage text in the center
        painter.setPen(QColor(255, 255, 255))  # White color for text
        painter.setFont(QFont("Arial", 16, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self.battery_percentage}%")

        painter.end()


class RoverGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("x0 Rover Controller (to the moon team)")
        self.ws = None
        
        # First initialize UI
        self.init_ui()
        
        # Clear any existing camera
        self.cap = None
        
        # Initialize webcam with a delay to ensure UI is ready
        QTimer.singleShot(1000, self.initialize_camera)

        QTimer.singleShot(0, self.start_async_connection)

        # Default speed values
        self.speed_factor = 1
        self.last_telemetry = {}

        # Keyboard controls
        self.pressed_keys = set()
        self.movement_timer = QTimer()
        self.movement_timer.timeout.connect(self.handle_movement_keys)
        self.movement_timer.start(100)
        self.setFocusPolicy(Qt.StrongFocus)

        # Initialize YOLO model with verbose=False to prevent terminal printing
        self.model = YOLO('yolov8n.pt', verbose=False)
        self.detection_enabled = False

        self.telemetry_logs = []  # Add this to store logs
        self.max_logs = 50  # Keep last 50 logs

    def init_ui(self):
        # Main layout
        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        # Left panel (controls)
        left_panel = QVBoxLayout()
        left_panel.setSpacing(15)
        left_panel.setContentsMargins(10, 10, 10, 10)

        # Right panel (camera and telemetry)
        right_panel = QVBoxLayout()  # Back to vertical layout
        right_panel.setSpacing(15)
        right_panel.setContentsMargins(10, 10, 10, 10)

        # Add panels to main layout
        main_layout.addLayout(left_panel, 30)  # 30% width
        main_layout.addLayout(right_panel, 70)  # 70% width

        # ========== LEFT PANEL CONTROLS ========== 
        
        # Battery status group
        battery_group = QGroupBox("Rover Status")
        battery_layout = QVBoxLayout()
        
        self.battery_widget = CircularProgress()
        battery_layout.addWidget(self.battery_widget, 0, Qt.AlignCenter)
        
        # Telemetry labels
        self.battery_label = QLabel("Battery: --%")
        self.imu_label = QLabel("Orientation: --")
        self.arm_label = QLabel("Arm Position: --")
        
        for label in [self.battery_label, self.imu_label, self.arm_label]:
            label.setStyleSheet("font-size: 12px;")
            battery_layout.addWidget(label)
        
        battery_group.setLayout(battery_layout)
        left_panel.addWidget(battery_group)

        # Speed control group
        speed_group = QGroupBox("Speed Control")
        speed_layout = QVBoxLayout()
        
        self.speed_display_label = QLabel("Current Speed: Normal")
        self.speed_display_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        speed_layout.addWidget(self.speed_display_label)
        
        # Speed buttons
        self.normal_speed_btn = self.create_speed_button("Normal Speed (1)", "normal")
        self.object_speed_btn = self.create_speed_button("Object Speed (2)", "object")
        self.fast_speed_btn = self.create_speed_button("Fast Speed (3)", "fast")
        
        speed_layout.addWidget(self.normal_speed_btn)
        speed_layout.addWidget(self.object_speed_btn)
        speed_layout.addWidget(self.fast_speed_btn)
        
        speed_group.setLayout(speed_layout)
        left_panel.addWidget(speed_group)

        # Movement controls group
        move_group = QGroupBox("Movement Controls (WASD/Arrows)")
        move_layout = QVBoxLayout()
        
        # Create a grid for movement buttons
        grid_layout = QGridLayout()
        grid_layout.setSpacing(5)
        
        # Movement buttons with larger size and better icons
        self.btn_fwd = self.create_movement_button("↑", "forward")
        self.btn_left = self.create_movement_button("←", "left")
        self.btn_right = self.create_movement_button("→", "right")
        self.btn_bwd = self.create_movement_button("↓", "backward")
        self.btn_stop = self.create_movement_button("◉", "stop")
        
        # Add buttons to grid
        grid_layout.addWidget(self.btn_fwd, 0, 1)
        grid_layout.addWidget(self.btn_left, 1, 0)
        grid_layout.addWidget(self.btn_stop, 1, 1)
        grid_layout.addWidget(self.btn_right, 1, 2)
        grid_layout.addWidget(self.btn_bwd, 2, 1)
        
        move_layout.addLayout(grid_layout)
        move_group.setLayout(move_layout)
        left_panel.addWidget(move_group)

        # Arm control group
        arm_group = QGroupBox("Arm Control (Q/E)")
        arm_layout = QVBoxLayout()
        
        self.arm_slider = QSlider(Qt.Horizontal)
        self.arm_slider.setMinimum(0)
        self.arm_slider.setMaximum(180)
        self.arm_slider.setValue(90)
        self.arm_slider.setTickInterval(10)
        self.arm_slider.setTickPosition(QSlider.TicksBelow)
        self.arm_slider.valueChanged.connect(self.arm_moved)
        
        self.lbl_arm = QLabel("Arm Angle: 90°")
        self.lbl_arm.setAlignment(Qt.AlignCenter)
        
        # Add Drop Flag button
        self.drop_flag_btn = QPushButton("Drop Flag (F)")
        self.drop_flag_btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxWarning))
        self.drop_flag_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                background-color: #d9534f;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c9302c;
            }
            QPushButton:pressed {
                background-color: #ac2925;
            }
        """)
        self.drop_flag_btn.clicked.connect(self.drop_flag)
        
        arm_layout.addWidget(self.lbl_arm)
        arm_layout.addWidget(self.arm_slider)
        arm_layout.addWidget(self.drop_flag_btn)
        arm_group.setLayout(arm_layout)
        left_panel.addWidget(arm_group)

        # Camera control group
        camera_control_group = QGroupBox("Camera Control (R/T)")
        camera_layout = QVBoxLayout()
        
        self.camera_slider = QSlider(Qt.Horizontal)
        self.camera_slider.setMinimum(-90)  # -90 degrees
        self.camera_slider.setMaximum(90)   # +90 degrees
        self.camera_slider.setValue(0)       # Start at center
        self.camera_slider.setTickInterval(15)
        self.camera_slider.setTickPosition(QSlider.TicksBelow)
        self.camera_slider.valueChanged.connect(self.camera_moved)
        
        self.lbl_camera = QLabel("Camera Angle: 0°")
        self.lbl_camera.setAlignment(Qt.AlignCenter)
        
        # Center camera button
        self.center_camera_btn = QPushButton("Center Camera (C)")
        self.center_camera_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                background-color: #5a8;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #496;
            }
            QPushButton:pressed {
                background-color: #385;
            }
        """)
        self.center_camera_btn.clicked.connect(self.center_camera)
        
        camera_layout.addWidget(self.lbl_camera)
        camera_layout.addWidget(self.camera_slider)
        camera_layout.addWidget(self.center_camera_btn)
        camera_control_group.setLayout(camera_layout)
        left_panel.addWidget(camera_control_group)

        # Media buttons
        media_group = QGroupBox("Media")
        media_layout = QHBoxLayout()
        
        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.screenshot_btn.clicked.connect(self.take_screenshot)
        
        self.take_photo_btn = QPushButton("Take Photo (P)")
        self.take_photo_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.take_photo_btn.clicked.connect(self.take_photo)
        
        # Add detection toggle button with 'O' shortcut
        self.detection_btn = QPushButton("Toggle Detection (O)")
        self.detection_btn.setCheckable(True)
        self.detection_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.detection_btn.clicked.connect(self.toggle_detection)
        
        media_layout.addWidget(self.screenshot_btn)
        media_layout.addWidget(self.take_photo_btn)
        media_layout.addWidget(self.detection_btn)
        media_group.setLayout(media_layout)
        left_panel.addWidget(media_group)

        # Add stretch to push everything up
        left_panel.addStretch()

        # ========== RIGHT PANEL CAMERA/TELEMETRY ========== 
        
        # Camera preview
        camera_group = QGroupBox("Camera Feed")
        camera_layout = QVBoxLayout()
        camera_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        
        self.camera_label = QLabel("Initializing camera...")
        self.camera_label.setMinimumSize(640, 480)  # Changed from setFixedSize to setMinimumSize
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # Allow expansion
        self.camera_label.setStyleSheet("""
            QLabel {
                border: 2px solid #444;
                border-radius: 5px;
                background: #222;
                color: #fff;
            }
        """)
        
        camera_layout.addWidget(self.camera_label, 1)  # Added stretch factor
        camera_group.setLayout(camera_layout)
        right_panel.addWidget(camera_group, 70)

        # Detailed telemetry
        telemetry_group = QGroupBox("Telemetry History")
        telemetry_layout = QVBoxLayout()
        
        self.telemetry_label = QLabel("Waiting for telemetry data...")
        self.telemetry_label.setWordWrap(True)
        self.telemetry_label.setStyleSheet("""
            font-family: monospace;
            background: #222;
            padding: 10px;
            border-radius: 5px;
            font-size: 11px;
            line-height: 1.2;
        """)
        
        # Add scroll area for telemetry with better styling
        scroll = QScrollArea()
        scroll.setWidget(self.telemetry_label)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #333;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #666;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        telemetry_layout.addWidget(scroll)
        telemetry_group.setLayout(telemetry_layout)
        right_panel.addWidget(telemetry_group, 30)

        # Apply styles
        self.apply_styles()

    def create_movement_button(self, text, direction):
        btn = QPushButton(text)
        btn.setFixedSize(60, 60)
        btn.setStyleSheet("""
            QPushButton {
                font-size: 24px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 30px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #444, stop:1 #333);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #666, stop:1 #555);
            }
        """)
        btn.clicked.connect(lambda: self.send_cmd("move", {"dir": direction}))
        return btn

    def create_speed_button(self, text, speed_type):
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                border: 1px solid #444;
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #555, stop:1 #444);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #777, stop:1 #666);
            }
        """)
        
        if speed_type == "normal":
            btn.clicked.connect(self.set_normal_speed)
        elif speed_type == "object":
            btn.clicked.connect(self.set_object_speed)
        elif speed_type == "fast":
            btn.clicked.connect(self.set_fast_speed)
        
        return btn

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                background: #333;
                color: #eee;
            }
            QGroupBox {
                border: 1px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #444;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                          stop:0 #eee, stop:1 #ccc);
                border: 1px solid #555;
                border-radius: 8px;
                margin: -4px 0;
            }
            QSlider::sub-page:horizontal {
                background: #5a8;
                border-radius: 4px;
            }
        """)

    def initialize_camera(self):
        """Initialize the webcam"""
        if self.cap is not None:
            self.cap.release()
        
        self.cap = cv2.VideoCapture(0)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)  # Back to larger resolution
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)  # Back to larger resolution
            self.telemetry_label.setText("Webcam initialized")
            
            # Start camera update timer
            if hasattr(self, 'camera_timer'):
                self.camera_timer.stop()
            self.camera_timer = QTimer()
            self.camera_timer.timeout.connect(self.update_camera)
            self.camera_timer.start(30)
        else:
            self.telemetry_label.setText("Failed to open webcam")
            self.camera_label.setText("No camera available")

    def update_camera(self):
        """Update the camera feed"""
        if self.cap is None or not self.cap.isOpened():
            self.camera_label.setText("Camera not available")
            return
        
        ret, frame = self.cap.read()
        if not ret:
            self.camera_label.setText("Failed to read camera frame")
            return
        
        try:
            if self.detection_enabled:
                results = self.model(frame, verbose=False)
                for result in results:
                    boxes = result.boxes
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cls = int(box.cls[0])
                        conf = float(box.conf[0])
                        name = result.names[cls]
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        label = f'{name} {conf:.2f}'
                        cv2.putText(frame, label, (x1, y1 - 10), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            # Convert to RGB for Qt
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Create QImage
            height, width, channel = rgb_frame.shape
            bytes_per_line = 3 * width
            q_image = QImage(rgb_frame.data, width, height, 
                            bytes_per_line, QImage.Format_RGB888).copy()
            
            # Scale to fill the entire label
            label_size = self.camera_label.size()
            scaled_pixmap = QPixmap.fromImage(q_image).scaled(
                label_size.width(),
                label_size.height(),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            )
            
            # Update the label
            self.camera_label.setPixmap(scaled_pixmap)
            
        except Exception as e:
            timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
            error_log = f"\n[{timestamp}] Error: {str(e)}"
            self.telemetry_logs.append(error_log)
            combined_logs = "".join(reversed(self.telemetry_logs))
            self.telemetry_label.setText(f"Telemetry History:\n{combined_logs}")

    def start_async_connection(self):
        asyncio.create_task(self.connect_websocket())

    async def connect_websocket(self):
        try:
            self.ws = await websockets.connect("ws://localhost:8765")
            self.telemetry_label.setText("Connected to Rover!")
            asyncio.create_task(self.receive_data())
        except Exception as e:
            self.telemetry_label.setText(f"Error connecting: {e}")

    def send_cmd(self, cmd_type, data):
        if self.ws:
            # Apply speed factor to movement commands
            if cmd_type == "move" and "speed" not in data:
                data["speed"] = self.speed_factor
                
            msg = {"cmd": cmd_type}
            msg.update(data)
            asyncio.create_task(self.ws.send(json.dumps(msg)))

    async def receive_data(self):
        try:
            while True:
                message = await self.ws.recv()
                telemetry = json.loads(message)
                self.last_telemetry = telemetry
                
                # Silently update the widgets
                battery = telemetry.get("battery", "--")
                self.battery_widget.set_battery_percentage(battery)
                self.battery_label.setText(f"Battery: {battery}%")
                
                imu = telemetry.get("imu", {})
                pitch = imu.get("pitch", "--")
                roll = imu.get("roll", "--")
                self.imu_label.setText(f"Orientation: Pitch {pitch}°, Roll {roll}°")
                
                arm = telemetry.get("arm", "--")
                self.arm_label.setText(f"Arm Position: {arm}°")
                
                # Add to telemetry history without printing
                timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
                log_entry = f"\n[{timestamp}] New telemetry data received"
                self.telemetry_logs.append(log_entry)
                
                if len(self.telemetry_logs) > self.max_logs:
                    self.telemetry_logs.pop(0)
                
                combined_logs = "".join(reversed(self.telemetry_logs))
                self.telemetry_label.setText(f"Telemetry History:\n{combined_logs}")
                
        except Exception as e:
            timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
            error_log = f"\n[{timestamp}] Connection error: {str(e)}"
            self.telemetry_logs.append(error_log)
            combined_logs = "".join(reversed(self.telemetry_logs))
            self.telemetry_label.setText(f"Telemetry History:\n{combined_logs}")

    def arm_moved(self, value):
        self.lbl_arm.setText(f"Arm Angle: {value}°")
        self.send_cmd("arm", {"joint": 1, "angle": value})

    def drop_flag(self):
        """Handle the drop flag command."""
        self.send_cmd("flag", {"action": "drop"})
        self.telemetry_label.setText("Flag dropped!")

    def set_normal_speed(self):
        self.speed_factor = 1
        self.speed_display_label.setText("Current Speed: Normal")
        self.update_speed_buttons("normal")

    def set_object_speed(self):
        self.speed_factor = 0.5
        self.speed_display_label.setText("Current Speed: Object")
        self.update_speed_buttons("object")

    def set_fast_speed(self):
        self.speed_factor = 2
        self.speed_display_label.setText("Current Speed: Fast")
        self.update_speed_buttons("fast")

    def update_speed_buttons(self, active):
        """Update button styles based on which speed is active"""
        buttons = {
            "normal": self.normal_speed_btn,
            "object": self.object_speed_btn,
            "fast": self.fast_speed_btn
        }
        
        for name, btn in buttons.items():
            if name == active:
                btn.setStyleSheet("""
                    QPushButton {
                        padding: 8px;
                        border: 2px solid #5a8;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #5a8, stop:1 #496);
                        font-weight: bold;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        padding: 8px;
                        border: 1px solid #444;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #555, stop:1 #444);
                    }
                """)

    def take_screenshot(self):
        """Capture and save a screenshot of the interface."""
        filename, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Screenshot", 
            "", 
            "JPEG Files (*.jpg);;PNG Files (*.png)"
        )
        if filename:
            screenshot = self.grab()
            screenshot.save(filename)

    def take_photo(self):
        """Capture a photo using the camera and save it."""
        ret, frame = self.cap.read()
        if ret:
            filename, _ = QFileDialog.getSaveFileName(
                self, 
                "Save Photo", 
                "", 
                "JPEG Files (*.jpg);;PNG Files (*.png)"
            )
            if filename:
                cv2.imwrite(filename, frame)  # Save frame to file
        else:
            self.telemetry_label.setText("Error capturing photo.")

    def toggle_detection(self):
        """Toggle object detection on/off"""
        self.detection_enabled = self.detection_btn.isChecked()
        status = "enabled" if self.detection_enabled else "disabled"
        
        # Add to telemetry history
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        log_entry = f"\n[{timestamp}] Object detection {status}"
        self.telemetry_logs.append(log_entry)
        
        # Update display
        combined_logs = "".join(reversed(self.telemetry_logs))
        self.telemetry_label.setText(f"Telemetry History:\n{combined_logs}")

    def keyPressEvent(self, event):
        """Handle key press events for movement controls."""
        key = event.key()
        
        # Movement keys (WASD and arrows)
        if key in (Qt.Key_W, Qt.Key_Up):
            self.pressed_keys.add('forward')
        elif key in (Qt.Key_S, Qt.Key_Down):
            self.pressed_keys.add('backward')
        elif key in (Qt.Key_A, Qt.Key_Left):
            self.pressed_keys.add('left')
        elif key in (Qt.Key_D, Qt.Key_Right):
            self.pressed_keys.add('right')
        
        # Speed control keys (1, 2, 3)
        elif key == Qt.Key_1:
            self.set_normal_speed()
        elif key == Qt.Key_2:
            self.set_object_speed()
        elif key == Qt.Key_3:
            self.set_fast_speed()
            
        # Arm control keys (Q/E for up/down)
        elif key == Qt.Key_Q:
            new_value = min(self.arm_slider.value() + 5, 180)
            self.arm_slider.setValue(new_value)
        elif key == Qt.Key_E:
            new_value = max(self.arm_slider.value() - 5, 0)
            self.arm_slider.setValue(new_value)
            
        # Space for stop
        elif key == Qt.Key_Space:
            self.pressed_keys.clear()
            self.send_cmd("move", {"dir": "stop"})
        
        # F for flag drop
        elif key == Qt.Key_F:
            self.drop_flag()
            
        # P for photo
        elif key == Qt.Key_P:
            self.take_photo()
            
        # Change to 'O' key for toggling detection
        elif key == Qt.Key_O:
            self.detection_btn.click()  # Simulate button click to toggle detection
            
        # Escape to exit
        elif key == Qt.Key_Escape:
            self.close()
            
        # Camera control keys (R/T for up/down)
        elif key == Qt.Key_R:
            new_value = min(self.camera_slider.value() + 5, 90)
            self.camera_slider.setValue(new_value)
        elif key == Qt.Key_T:
            new_value = max(self.camera_slider.value() - 5, -90)
            self.camera_slider.setValue(new_value)
        elif key == Qt.Key_C:
            self.center_camera()
            
        event.accept()

    def keyReleaseEvent(self, event):
        """Handle key release events."""
        key = event.key()
        
        if key in (Qt.Key_W, Qt.Key_Up):
            self.pressed_keys.discard('forward')
        elif key in (Qt.Key_S, Qt.Key_Down):
            self.pressed_keys.discard('backward')
        elif key in (Qt.Key_A, Qt.Key_Left):
            self.pressed_keys.discard('left')
        elif key in (Qt.Key_D, Qt.Key_Right):
            self.pressed_keys.discard('right')
            
        # If no movement keys are pressed, stop the rover
        if not self.pressed_keys:
            self.send_cmd("move", {"dir": "stop"})
            
        event.accept()

    def handle_movement_keys(self):
        """Handle continuous movement based on pressed keys."""
        if not self.pressed_keys:
            return
            
        # Determine primary direction based on pressed keys
        if 'forward' in self.pressed_keys and 'left' in self.pressed_keys:
            direction = "forward_left"
        elif 'forward' in self.pressed_keys and 'right' in self.pressed_keys:
            direction = "forward_right"
        elif 'backward' in self.pressed_keys and 'left' in self.pressed_keys:
            direction = "backward_left"
        elif 'backward' in self.pressed_keys and 'right' in self.pressed_keys:
            direction = "backward_right"
        elif 'forward' in self.pressed_keys:
            direction = "forward"
        elif 'backward' in self.pressed_keys:
            direction = "backward"
        elif 'left' in self.pressed_keys:
            direction = "left"
        elif 'right' in self.pressed_keys:
            direction = "right"
        else:
            direction = "stop"
            
        self.send_cmd("move", {"dir": direction})

    def closeEvent(self, event):
        """Clean up resources when closing"""
        if self.cap is not None:
            self.cap.release()
        if self.ws:
            asyncio.get_event_loop().run_until_complete(self.ws.close())
        event.accept()

    def camera_moved(self, value):
        """Handle camera angle changes"""
        self.lbl_camera.setText(f"Camera Angle: {value}°")
        self.send_cmd("camera", {"angle": value})
        
        # Add to telemetry history
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        log_entry = f"\n[{timestamp}] Camera rotated to {value}°"
        self.telemetry_logs.append(log_entry)
        combined_logs = "".join(reversed(self.telemetry_logs))
        self.telemetry_label.setText(f"Telemetry History:\n{combined_logs}")

    def center_camera(self):
        """Center the camera (0 degrees)"""
        self.camera_slider.setValue(0)
        self.send_cmd("camera", {"angle": 0})
        
        # Add to telemetry history
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        log_entry = f"\n[{timestamp}] Camera centered"
        self.telemetry_logs.append(log_entry)
        combined_logs = "".join(reversed(self.telemetry_logs))
        self.telemetry_label.setText(f"Telemetry History:\n{combined_logs}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Set dark palette
    app.setStyle('Fusion')
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(35, 35, 35))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)

    window = RoverGUI()
    window.showMaximized()

    with loop:
        loop.run_forever()