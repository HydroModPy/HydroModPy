# -*- coding: utf-8 -*-
"""
Created on Mon Mar 10 13:59:17 2025

@author: delarueo
"""

import numpy as np
import cv2
import matplotlib.pyplot as plt

def create_polygon_mask(image_shape, polygon_points):
    """
    Creates a binary mask for the given polygon.

    :param image_shape: Shape of the image (height, width)
    :param polygon_points: List of (x, y) tuples representing the polygon vertices
    :return: Binary mask (image with 1s inside the polygon, 0s outside)
    """
    # Create a black image of the same size as the input image
    mask = np.zeros(image_shape, dtype=np.uint8)
    
    # Convert the polygon points to an array of integer coordinates
    polygon_points = np.array(polygon_points, np.int32)
    polygon_points = polygon_points.reshape((-1, 1, 2))
    
    # Fill the polygon on the mask (the polygon will be white)
    cv2.fillPoly(mask, [polygon_points], 255)
    
    return mask

def expand_polygon_mask(mask, kernel_size=10):
    """
    Expands the polygon region using dilation to ensure complete coverage.
    
    :param mask: The binary mask of the polygon
    :param kernel_size: Size of the kernel used for dilation
    :return: Expanded binary mask
    """
    # Create a kernel (square or elliptical shape for dilation)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    
    # Apply dilation to expand the polygon area
    expanded_mask = cv2.dilate(mask, kernel, iterations=1)
    
    return expanded_mask

def extract_pixels_in_polygon(image, polygon_points, kernel_size=10):
    """
    Extracts the pixels inside the expanded polygon from an image.
    
    :param image: Input image (numpy array)
    :param polygon_points: List of (x, y) tuples representing the polygon vertices
    :param kernel_size: Size of the dilation kernel to expand the polygon
    :return: Array of pixels inside the expanded polygon
    """
    # Create the initial mask for the polygon
    mask = create_polygon_mask(image.shape[:2], polygon_points)
    
    # Expand the polygon region using dilation
    expanded_mask = expand_polygon_mask(mask, kernel_size)
    
    # Apply the expanded mask to the image
    result = cv2.bitwise_and(image, image, mask=expanded_mask)
    
    return result

# Example usage:
# Define an image (for example, a simple black square with a white circle inside)
image = np.zeros((500, 500, 3), dtype=np.uint8)
cv2.circle(image, (250, 250), 100, (255, 255, 255), -1)

# Define the polygon (e.g., a triangle inside the image)
polygon_points = [(100, 100), (400, 100), (250, 400)]

# Extract the pixels inside the expanded polygon
polygon_pixels = extract_pixels_in_polygon(image, polygon_points, kernel_size=20)

# Display the result
plt.imshow(cv2.cvtColor(polygon_pixels, cv2.COLOR_BGR2RGB))
plt.axis('off')
plt.show()
