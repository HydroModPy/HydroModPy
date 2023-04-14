<?xml version="1.0" encoding="UTF-8"?>
<structure version="2" schemafile="basic_scheme.dtd" workingxmlfile="" templatexmlfile="">
	<template>
		<match overwrittenxslmatch="/"/>
		<children>
			<paragraph paragraphtag="h1">
				<properties align="center"/>
				<children>
					<text fixtext="Edition of parameters"/>
				</children>
			</paragraph>
			<newline/>
			<table>
				<properties border="0" width="100%"/>
				<children>
					<tablebody>
						<children>
							<tablerow>
								<properties bgcolor="#C0C0C0"/>
								<children>
									<tablecol>
										<properties align="center" width="20%"/>
										<children>
											<text fixtext="name">
												<styles font-weight="bold"/>
											</text>
										</children>
									</tablecol>
									<tablecol>
										<properties align="center" width="10%"/>
										<children>
											<text fixtext="type"/>
										</children>
									</tablecol>
									<tablecol>
										<properties align="center" width="10%"/>
										<children>
											<text fixtext="value"/>
										</children>
									</tablecol>
									<tablecol>
										<properties align="center" width="10%"/>
										<children>
											<text fixtext="default_value"/>
										</children>
									</tablecol>
									<tablecol>
										<properties align="center" width="30%"/>
										<children>
											<text fixtext="possible_values"/>
										</children>
									</tablecol>
									<tablecol>
										<properties align="center" width="20%"/>
										<children>
											<text fixtext="description"/>
										</children>
									</tablecol>
								</children>
							</tablerow>
						</children>
					</tablebody>
				</children>
			</table>
			<newline/>
			<xpath allchildren="1"/>
		</children>
	</template>
	<template>
		<match match="Parameter"/>
		<children>
			<table>
				<properties border="0" width="100%"/>
				<children>
					<tablebody>
						<children>
							<tablerow>
								<properties bgcolor="#E0E0E0"/>
								<children>
									<tablecol>
										<properties width="20%"/>
										<children>
											<template>
												<match match="@name"/>
												<children>
													<xpath allchildren="1">
														<styles font-weight="bold"/>
													</xpath>
												</children>
											</template>
										</children>
									</tablecol>
									<tablecol>
										<properties width="10%"/>
										<children>
											<template>
												<match match="type"/>
												<children>
													<xpath allchildren="1"/>
												</children>
											</template>
										</children>
									</tablecol>
									<tablecol>
										<properties width="10%"/>
										<children>
											<template>
												<match match="value"/>
												<children>
													<xpath allchildren="1"/>
												</children>
											</template>
										</children>
									</tablecol>
									<tablecol>
										<properties width="10%"/>
										<children>
											<template>
												<match match="default_value"/>
												<children>
													<xpath allchildren="1"/>
												</children>
											</template>
										</children>
									</tablecol>
									<tablecol>
										<properties width="30%"/>
										<children>
											<template>
												<match match="possible_values"/>
												<children>
													<xpath allchildren="1"/>
												</children>
											</template>
										</children>
									</tablecol>
									<tablecol>
										<properties width="20%"/>
										<children>
											<template>
												<match match="description"/>
												<children>
													<xpath allchildren="1"/>
												</children>
											</template>
										</children>
									</tablecol>
								</children>
							</tablerow>
						</children>
					</tablebody>
				</children>
			</table>
		</children>
	</template>
	<template>
		<match match="ParametersGroup"/>
		<children>
			<template>
				<match match="@name"/>
				<children>
					<xpath allchildren="1">
						<styles font-weight="bold" text-decoration="underline"/>
					</xpath>
				</children>
			</template>
			<newline/>
			<xpath allchildren="1"/>
			<text fixtext="end ">
				<styles font-style="italic"/>
			</text>
			<template>
				<match match="@name"/>
				<children>
					<xpath allchildren="1">
						<styles font-style="italic"/>
					</xpath>
				</children>
			</template>
			<newline/>
			<newline/>
		</children>
	</template>
</structure>
