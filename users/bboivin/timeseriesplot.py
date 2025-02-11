# -*- coding: utf-8 -*-
"""
Developped by Bastien Boivin(2025)
"""
#%%
import pandas as pd
import plotly.offline as pyo
import plotly.graph_objects as go

class TimeSeriesPlot:
    """
    A class for creating and displaying time series plots using Plotly.
    The TimeSeriesPlot class allows users to add time series data, vertical and horizontal lines,
    and rectangles to a plot. It provides methods to configure the plot's title, axis titles, axis ranges,
    and logarithmic scaling. The plot can be displayed in a web browser or directly within a Python environment.
    """
    def __init__(self, title: str, x_axis_title: str, y_axis_title: str,
                 x_range: tuple, log_x: bool = False, log_y: bool = False):
        self.title = title
        self.x_axis_title = x_axis_title
        self.y_axis_title = y_axis_title
        self.x_range = x_range
        self.log_x = log_x
        self.log_y = log_y
        self.series_list = []
        self.line_list = []
        self.rectangle_list = []
    
    def add_series(self, df: pd.DataFrame, time_col: str, var_col, color: str, mode: str = 'lines',
                   legend_name: str = None, year_min: int = None, year_max: int = None):
        """
        Add a time series to the internal list after processing the provided DataFrame.
        This function converts the specified time column to datetime format, applies optional
        year-based filtering, and prepares the series information to be appended to the internal
        series_list for later plotting.
        Parameters
        ----------
        df : pd.DataFrame
            The DataFrame containing the time series data.
        time_col : str
            The name of the column in the DataFrame representing datetime information.
        var_col : str
            The name of the variable column in the DataFrame.
        color : str
            The color to be used for plotting the series.
        mode : str, optional
            The mode of the plot, by default 'lines'.
        legend_name : str, optional
            The name to be used in the plot legend. If None, the string representation of var_col is used.
        year_min : int, optional
            The minimum year (inclusive) to filter the DataFrame. If None, no lower year bound is applied.
        year_max : int, optional
            The maximum year (inclusive) to filter the DataFrame. If None, no upper year bound is applied.
        Returns
        -------
        None
            This method appends the processed series information to the series_list attribute.
        """
        df[time_col] = pd.to_datetime(df[time_col])
        if year_min is not None:
            df = df[df[time_col].dt.year >= year_min]
        if year_max is not None:
            df = df[df[time_col].dt.year <= year_max]
        
        if legend_name is None:
            legend_name = str(var_col)

        self.series_list.append({
            'df': df,
            'time_col': time_col,
            'var_col': var_col,
            'color': color,
            'mode': mode,
            'legend_name': legend_name
        })
        
    def add_line(self, orientation: str, position: float, line_dash: str, col: str = 'all',
                 color: str = 'black', label: str = ''):
        """
        Add a new line to the plot configuration.

        This method appends a dictionary containing line parameters to the internal
        line_list. The dictionary stores the orientation, position, dash style,
        associated column, color, and label for the line to be plotted.

        Parameters
        ----------
        orientation : str
            The orientation of the line. This may represent a specific direction or
            reference for positioning.
        position : int or float
            The position along the axis where the line will be drawn.
        line_dash : str
            The dash style of the line (e.g., 'solid', 'dash', 'dot').
        col : str, optional
            The column associated with the line. Defaults to 'all' if not specified.
        color : str
            The color of the line.
        label : str
            A label for the line, useful for legends or annotations.

        Returns
        -------
        None
        """
        self.line_list.append({
            'orientation': orientation,
            'position': position,
            'line_dash': line_dash,
            'col': col,
            'color': color,
            'label': label
        })
        
    def add_rectangle(self, orientation: str, x0: float = None, x1: float = None, y0: float = None,
                      y1: float = None, color: str = 'black', opacity: float = 0.2, label: str = ''):
        """
        Adds a rectangle to the plot with the specified properties.

        Parameters
        ----------
        orientation : str
            The orientation of the rectangle ('horizontal' or 'vertical').
        x0 : float, optional
            The starting x-coordinate of the rectangle. Default is None.
        x1 : float, optional
            The ending x-coordinate of the rectangle. Default is None.
        y0 : float, optional
            The starting y-coordinate of the rectangle. Default is None.
        y1 : float, optional
            The ending y-coordinate of the rectangle. Default is None.
        color : str
            The color of the rectangle.
        opacity : float, optional
            The opacity of the rectangle, ranging from 0 to 1. Default is 0.2.
        label : str
            The label for the rectangle.

        Returns
        -------
        None
        """
        self.rectangle_list.append({
            'orientation': orientation,
            'x0': x0,
            'x1': x1,
            'y0': y0,
            'y1': y1,
            'color': color,
            'opacity': opacity,
            'label': label
        })
    
    def create_figure(self) -> go.Figure:
        """
        Create a Plotly figure with time series data, vertical and horizontal lines, and rectangles.
        Returns
        -------
        go.Figure
            A Plotly figure object containing the time series plot.
        Notes
        -----
        - The method iterates over `self.series_list` to add time series data to the figure.
        - Vertical and horizontal lines are added from `self.line_list`.
        - Vertical and horizontal rectangles are added from `self.rectangle_list`.
        - The x-axis range can be set using `self.x_range`.
        - The y-axis can be set to logarithmic scale if `self.log_y` is True.
        - The layout of the figure is updated with titles, axis properties, legend, and background color.
        """
        fig = go.Figure()
        for series in self.series_list:
            df = series['df']
            time_col = series['time_col']
            var_col = series['var_col']
            color = series['color']
            mode = series['mode']
            legend_name = series['legend_name']
            
            if isinstance(var_col, int):
                y_data = df.iloc[:, var_col]
            else:
                y_data = df[var_col]
            
            if self.log_y:
                y_data = y_data.copy()
                y_data = y_data.where(y_data > 0)
            
            fig.add_trace(go.Scatter(
                x=df[time_col],
                y=y_data,
                mode=mode,
                name=legend_name,
                line=dict(color=color)
            ))
        
        for line in self.line_list:
            if line['orientation'] == 'v':
                fig.add_vline(x=line['position'],
                              line_dash=line['line_dash'],
                              line_color=line['color'],
                              label=dict(
                                  text=line['label'],
                                  textangle=0,
                                  textposition='end',
                                  font=dict(size=10, color=line['color']),
                                  yanchor='top',
                                  xanchor='left'
                              )
                              )
            elif line['orientation'] == 'h':
                fig.add_hline(y=line['position'],
                              line_dash=line['line_dash'],
                              line_color=line['color'],
                              label=dict(
                                  text=line['label'],
                                  textposition='start',
                                  font=dict(size=10, color=line['color']),
                                  xanchor='left'
                              )
                              )
        
        for rect in self.rectangle_list:
            if rect['orientation'] == 'v':
                fig.add_vrect(
                    x0=rect['x0'],
                    x1=rect['x1'],
                    fillcolor=rect['color'],
                    opacity=rect['opacity'],
                    layer='below',
                    line_width=0,
                    annotation_text=rect['label'],
                    annotation_position='top left'
                    )
            elif rect['orientation'] == 'h':
                fig.add_vrect(
                    y0=rect['y0'],
                    y1=rect['y1'],
                    fillcolor=rect['color'],
                    opacity=rect['opacity'],
                    layer='below',
                    line_width=0,
                    annotation_text=rect['label'],
                    annotation_position='top left'
                    )
                
        if self.x_range:
            start_year, end_year = self.x_range
            x_range = [f"{start_year}-01-01", f"{end_year}-12-31"]
        else:
            x_range = None

        fig.update_layout(
            title=self.title,
            xaxis_title=self.x_axis_title,
            yaxis_title=self.y_axis_title,
            xaxis=dict(
                type='date',
                range=x_range
            ),
            yaxis=dict(
                type='log' if self.log_y else 'linear'
            ),
            legend=dict(
                title="Légende",
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
                
            ),
            plot_bgcolor='white',
            hovermode='x unified'
        )

        fig.update_xaxes(
            mirror=True,
            ticks='outside',
            showline=True,
            linecolor='black',
            gridcolor='lightgrey'
        )
        fig.update_yaxes(
            mirror=True,
            ticks='outside',
            showline=True,
            linecolor='black',
            gridcolor='lightgrey'
        )

        return fig

    def show(self, open_browser: bool = False):
        """
        Display the time series plot.

        Parameters
        ----------
        open_browser : bool, optional
            If True, the plot will be opened in a web browser using Plotly's `pyo.plot` function. 
            If False, the plot will be displayed using the `fig.show` method. Default is False.

        Returns
        -------
        None
        """
        fig = self.create_figure()
        if open_browser:
            pyo.plot(fig, auto_open=True)
        else:
            fig.show()

#%% Plot Test
if __name__ == '__main__':
    def test_time_series_plot():
        # Create sample data
        dates = pd.date_range(start="2000-01-01", end="2020-12-31", freq='Y')
        df1 = pd.DataFrame({
            'date': dates,
            'value': [i for i in range(len(dates))]
        })

        df2 = pd.DataFrame({
            'date': dates,
            'value': [i**2 for i in range(len(dates))]
        })

        # Initialize the plot
        plot = TimeSeriesPlot(
            title="Time Series Example",
            x_axis_title="Date",
            y_axis_title="Value",
            x_range=(2000, 2020),
            log_x=False,
            log_y=False
        )

        # Add series
        plot.add_series(
            df1,
            time_col='date',
            var_col='value',
            color='blue',
            mode='lines',
            legend_name="Linear Growth",
            year_min=2005
        )

        plot.add_series(
            df2,
            time_col='date',
            var_col='value',
            color='red',
            mode='markers',
            legend_name="Quadratic Growth"
        )

        # Add lines
        plot.add_line(orientation='v',
                      position='2010-01-01',
                      line_dash='dash',
                      color='green',
                      label='Vertical Line'
                      )

        plot.add_line(orientation='h',
                      position=100,
                      line_dash='dot',
                      color='purple',
                      label='Horizontal Line'
                      )

        # Add rectangle
        plot.add_rectangle(orientation='v',
                           x0='2015-01-01', x1='2017-12-31',
                           color='green',
                           opacity=0.2,
                           label='Rectangle'
                           )

        # Display the plot
        plot.show(open_browser=True)

    # Run the test
    test_time_series_plot()

# %%
