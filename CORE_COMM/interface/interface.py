# -*- coding: utf-8 -*-
"""
Created on Tue Mar 29 17:26:41 2022

@author: Alexandre Gauvain
"""

#%%
from PyQt5 import QtWidgets, QtWebEngineWidgets
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5.QtWidgets import QApplication, QSpinBox, QAction, QToolBar, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,QLabel, QMenuBar, QMenu
from PyQt5.QtWebEngineWidgets import QWebEngineView 
from PyQt5.QtWidgets import QToolBar, QFileDialog

import sys
import io
import folium
import os
import platform

CORE_COMM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HydroModPy = os.path.dirname(CORE_COMM)

class MyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initWindow()
        self.path = os.path.abspath(os.path.dirname(sys.argv[0]))
        self.pathOutput = os.path.join(self.path, "output")

    def initWindow(self):
        self.setWindowTitle('HydroModPy App')
        self.setWindowIcon(QtGui.QIcon(os.path.join(HydroModPy,'docs','source','images','logoHydroModPy.ico')))
        self.window_width, self.window_height = 1080, 900
        self.setMinimumSize(self.window_width, self.window_height)
        self.buttonUI()
        self._createActions()
        self._createMenuBar()
        self._createToolBars()
        self._createStatusBar()


    def _createMenuBar(self):
        menuBar = self.menuBar()
        # Creating menus using a QMenu object
        fileMenu = QMenu("&File", self)
        menuBar.addMenu(fileMenu)
        fileMenu.addAction(self.newAction)
        fileMenu.addAction(self.openAction)
        fileMenu.addAction(self.saveAction)
        fileMenu.addAction(self.exitAction)
        # Creating menus using a title
        editMenu = menuBar.addMenu("&Edit")
        editMenu.addAction(self.copyAction)
        editMenu.addAction(self.pasteAction)
        editMenu.addAction(self.cutAction)
        findMenu = editMenu.addMenu("Find and Replace")
        findMenu.addAction("Find...")
        findMenu.addAction("Replace...")
        helpMenu = menuBar.addMenu("&Help")
        helpMenu.addAction(self.helpContentAction)
        helpMenu.addAction(self.aboutAction)
    
    def _createActions(self):
        # Creating action using the first constructor
        self.newAction = QAction(self)
        self.newAction.setText("&New")
        # Creating actions using the second constructor
        self.openAction = QAction("&Open...", self)
        self.saveAction = QAction("&Save", self)
        self.exitAction = QAction("&Exit", self)
        self.copyAction = QAction("&Copy", self)
        self.pasteAction = QAction("&Paste", self)
        self.cutAction = QAction("C&ut", self)
        self.helpContentAction = QAction("&Help Content", self)
        self.aboutAction = QAction("&About", self)

    def _createStatusBar(self):
        self.statusbar = self.statusBar()
        # Adding a temporary message
        self.statusbar.showMessage("Ready", 3000)


    def _createToolBars(self):
        # Using a title
        fileToolBar = self.addToolBar("File")
        self.fontSizeSpinBox = QSpinBox()
        self.fontSizeSpinBox.setFocusPolicy(QtCore.Qt.NoFocus)
        fileToolBar.addWidget(self.fontSizeSpinBox)
        fileToolBar.setMovable(False)
        # Using a QToolBar object
        editToolBar = QToolBar("Edit", self)
        self.addToolBar(editToolBar)
        # Using a QToolBar object and a toolbar area
        helpToolBar = QToolBar("Help", self)
        self.addToolBar(QtCore.Qt.LeftToolBarArea, helpToolBar)

    def open_explorer(self):
        self._process = QtCore.QProcess(self)
        if platform.system() == "Windows":
            self._process.start("explorer",[os.path.realpath(self.pathOutput)])
        elif platform.system() == "Darwin":
            self._process.start("open",[os.path.realpath(self.pathOutput)])

    def select_outputfolder(self):
        
        test = QFileDialog.getExistingDirectory(self,"Choose Directory","C:\\")
        print(test)

    def buttonUI(self):
        shortPathButton = QtWidgets.QPushButton(self.tr("Open model folder"))
        shortPathButton.clicked.connect(self.open_explorer)

        button2 = QtWidgets.QPushButton(self.tr("select_outputfolder"))
        button2.clicked.connect(self.select_outputfolder)
        button3 = QtWidgets.QPushButton(self.tr("Another path"))
        
        shortPathButton.setFixedSize(120, 50)
        button2.setFixedSize(120, 50)
        button3.setFixedSize(120, 50)

        self.view = QtWebEngineWidgets.QWebEngineView()
        self.view.setContentsMargins(50, 50, 50, 50)

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        lay = QtWidgets.QHBoxLayout(central_widget)

        button_container = QtWidgets.QWidget()
        vlay = QtWidgets.QVBoxLayout(button_container)
        vlay.setSpacing(20)
        vlay.addStretch()
        vlay.addWidget(shortPathButton)
        vlay.addWidget(button2)
        vlay.addWidget(button3)
        vlay.addStretch()
        lay.addWidget(button_container)
        lay.addWidget(self.view, stretch=1)

        m = folium.Map(
            location=[46.856578, 2.351828], zoom_start=6
        )#, tiles="Stamen Toner"

        data = io.BytesIO()
        m.save(data, close_file=False)
        self.view.setHtml(data.getvalue().decode())

    


if __name__ == '__main__':
    app = QApplication(sys.argv)
    #app.setStyleSheet('''QWidget {font-size: 3px;}''')
    
    myApp = MyApp()
    myApp.show()

    try:
        sys.exit(app.exec_())
    except SystemExit:
        print('Closing Window...')






















