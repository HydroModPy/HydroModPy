# -*- coding: utf-8 -*-
"""
Created on Tue Mar 29 17:26:41 2022

@author: Alexandre Gauvain
"""

#%%
from PyQt5 import QtWidgets
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView 
import sys
import io
import folium



class MyApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('HydroModPy App')
        self.setWindowIcon(QtGui.QIcon('C:/Users/geoso/Documents/Geosophy/logoHydroModPy.ico'))
        self.window_width, self.window_height = 1080, 900
        self.setMinimumSize(self.window_width, self.window_height)

        layout = QVBoxLayout()
        self.setLayout(layout)
        
        
        label = QLabel(self)
        label.setText("test")
        label.move(50,50)
        
        button1 = QtWidgets.QPushButton("One")
        layout.addWidget(button1)
       

        coordinate = (37.8199286, -122.4782551)
        m = folium.Map(
        	tiles='Stamen Terrain',
        	zoom_start=13,
        	location=coordinate
        )

        # save map data to data object
        data = io.BytesIO()
        m.save(data, close_file=False)

        webView = QWebEngineView()
        webView.setHtml(data.getvalue().decode())
        layout.addWidget(webView)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet('''
        QWidget {
            font-size: 35px;
        }
    ''')
    
    myApp = MyApp()
    myApp.show()

    try:
        sys.exit(app.exec_())
    except SystemExit:
        print('Closing Window...')






















