Here is Claude's plan:
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Plan: Generación de dead-inventory-by-day.csv

 Objetivo

 Crear un script que procese el archivo consolidado.csv y genere dead-inventory-by-day.csv con alertas de stock inmovilizado (simulando día a día lo que hubiera
 surgido).

 Estructura de Datos de Entrada

 Archivo: data-preparation/output/consolidado.csv

 | Columna                 | Uso                             |
 |-------------------------|---------------------------------|
 | Fecha                   | Fecha del registro (DD/MM/YYYY) |
 | Item Nbr                | Identificador del producto      |
 | Item Desc 1             | Descripción del producto        |
 | UPC                     | Código EAN                      |
 | Store Nbr               | Número de tienda                |
 | Store Name              | Nombre de tienda                |
 | POS Qty                 | Ventas en unidades              |
 | POS Sales               | Ventas en monto ($)             |
 | Curr Str On Hand Qty    | Stock actual                    |
 | Curr Str In Transit Qty | Stock en tránsito               |

 Estructura de Datos de Salida

 Archivo: data-preparation/output/dead-inventory-by-day.csv

 | Columna                 | Descripción                                         |
 |-------------------------|-----------------------------------------------------|
 | Fecha                   | Fecha de la iteración evaluada                      |
 | Item Nbr                | Número de ítem                                      |
 | Item Desc 1             | Descripción del ítem                                |
 | UPC                     | Código EAN                                          |
 | Store Nbr               | Número del punto de venta                           |
 | Store Name              | Nombre del punto de venta                           |
 | Alarma                  | "Stock Inmovilizado" o "Mala exhibición"            |
 | Sell out Promedio Un.   | Venta promedio en unidades (14 días previos)        |
 | Sell out Promedio $     | Venta promedio en monto (14 días previos)           |
 | Días de alarma          | Cantidad de días consecutivos en esta situación     |
 | Severidad               | Valor 1-10 (suma de quintiles de producto y tienda) |
 | Curr Str In Transit Qty | Stock en tránsito                                   |

 Algoritmo

 Paso 1: Carga y Preparación de Datos

 1. Leer consolidado.csv completo
 2. Parsear fechas de formato DD/MM/YYYY a objetos Date
 3. Ordenar registros por fecha
 4. Identificar rango de fechas disponibles

 Paso 2: Indexación por Combinación UPC+Store

 1. Crear estructura de datos: Map<"UPC|StoreNbr", Array<RegistroDiario>>
 2. Cada registro diario contiene: fecha, POS Qty, POS Sales, stock, etc.
 3. Ordenar cada array por fecha ascendente

 Paso 3: Filtrar Combinaciones con Historia Suficiente

 1. Para cada combinación UPC+Store, verificar que tenga al menos 15 días de datos
 2. Descartar combinaciones con menos de 15 días

 Paso 4: Iteración Día a Día (desde día 15 en adelante)

 Para cada día D (comenzando en el día 15 hasta el último día):

 4.1 Calcular Rankings Dinámicos (basados en 14 días previos)

 - Ranking de Producto: Suma de POS Sales por Item Nbr en los días D-14 a D-1
 - Ranking de Tienda: Suma de POS Sales por Store Nbr en los días D-14 a D-1
 - Dividir cada ranking en quintiles (1=top 20%, 5=bottom 20%)

 4.2 Evaluar cada combinación UPC+Store

 Para cada combinación con datos en el día D y D-1:

 1. Verificar condición de stock inmovilizado:
   - Día D: POS Qty = 0 AND Curr Str On Hand Qty > 0
   - Día D-1: POS Qty = 0 AND Curr Str On Hand Qty > 0
 2. Si hay stock inmovilizado, determinar tipo de alarma:
   - Si Stock(D) > Stock(D-1) → "Mala exhibición" (el stock subió sin ventas)
   - Caso contrario → "Stock Inmovilizado"
 3. Calcular días de alarma:
   - Contar días consecutivos hacia atrás (desde D) con la misma condición
 4. Calcular promedios (14 días previos):
   - Sell out Promedio Un. = Promedio de POS Qty de días D-14 a D-1
   - Sell out Promedio $ = Promedio de POS Sales de días D-14 a D-1
 5. Calcular severidad:
   - Obtener quintil del producto (1-5)
   - Obtener quintil de la tienda (1-5)
   - Severidad = quintil_producto + quintil_tienda (rango 2-10, normalizar a 1-10)

 Paso 5: Generación del Output

 1. Escribir header del CSV
 2. Escribir cada alarma detectada como una fila
 3. Guardar en data-preparation/output/dead-inventory-by-day.csv

 Consideraciones Técnicas

 Manejo de Valores N/A

 - Curr Str On Hand Qty puede ser "N/A" → tratarlo como 0 (sin stock conocido, no genera alarma)

 Formato de Fechas

 - Entrada: DD/MM/YYYY
 - Mantener mismo formato en salida

 Performance

 - El archivo tiene ~446K registros
 - Usar estructuras de datos eficientes (Maps para lookups)
 - Procesar secuencialmente por fecha para evitar recálculos innecesarios

 Cálculo de Quintiles

 - Quintil 1: Top 20% (mejor ranking, mayor prioridad)
 - Quintil 5: Bottom 20%
 - La prioridad final va de 2 (1+1) a 10 (5+5)
 - Mapear: Severidad = (quintil_producto + quintil_tienda) - 1 → rango 1-9, ajustar si necesario

 Archivo a Crear

 Ruta: data-preparation/generate-dead-inventory.js

 Seguir el patrón del archivo existente process-walmart-data.js:
 - Usar ES Modules (import/export)
 - Usar fs/promises para operaciones de archivo
 - Parsear CSV manualmente o usar librería csv-parse si está disponible

 Dependencias

 - csv-parse (v5.6.0) - Ya disponible en package.json
 - fs/promises - Nativo de Node.js

 Script npm (agregar a package.json)

 "generate-dead-inventory": "node generate-dead-inventory.js"
