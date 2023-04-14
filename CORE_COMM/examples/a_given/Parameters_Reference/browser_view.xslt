<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
	<xsl:template match="/">
		<html>
			<head/>
			<body>
				<h1 align="center">Edition of parameters</h1>
				<br/>
				<table border="0" width="100%">
					<tbody>
						<tr bgcolor="#C0C0C0">
							<td align="center" width="20%">
								<span style="font-weight:bold">name</span>
							</td>
							<td align="center" width="10%">type</td>
							<td align="center" width="10%">value</td>
							<td align="center" width="10%">default_value</td>
							<td align="center" width="30%">possible_values</td>
							<td align="center" width="20%">description</td>
						</tr>
					</tbody>
				</table>
				<br/>
				<xsl:apply-templates/>
			</body>
		</html>
	</xsl:template>
	<xsl:template match="Parameter">
		<table border="0" width="100%">
			<tbody>
				<tr bgcolor="#E0E0E0">
					<td width="20%">
						<xsl:for-each select="@name">
							<span style="font-weight:bold">
								<xsl:value-of select="."/>
							</span>
						</xsl:for-each>
					</td>
					<td width="10%">
						<xsl:for-each select="type">
							<xsl:apply-templates/>
						</xsl:for-each>
					</td>
					<td width="10%">
						<xsl:for-each select="value">
							<xsl:apply-templates/>
						</xsl:for-each>
					</td>
					<td width="10%">
						<xsl:for-each select="default_value">
							<xsl:apply-templates/>
						</xsl:for-each>
					</td>
					<td width="30%">
						<xsl:for-each select="possible_values">
							<xsl:apply-templates/>
						</xsl:for-each>
					</td>
					<td width="20%">
						<xsl:for-each select="description">
							<xsl:apply-templates/>
						</xsl:for-each>
					</td>
				</tr>
			</tbody>
		</table>
	</xsl:template>
	<xsl:template match="ParametersGroup">
		<xsl:for-each select="@name">
			<span style="font-weight:bold; text-decoration:underline">
				<xsl:value-of select="."/>
			</span>
		</xsl:for-each>
		<br/>
		<xsl:apply-templates/>
		<span style="font-style:italic">end </span>
		<xsl:for-each select="@name">
			<span style="font-style:italic">
				<xsl:value-of select="."/>
			</span>
		</xsl:for-each>
		<br/>
		<br/>
	</xsl:template>
</xsl:stylesheet>
