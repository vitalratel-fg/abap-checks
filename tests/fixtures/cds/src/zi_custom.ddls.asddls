define custom entity zi_custom {
  key k : abap.char(1);
  @ObjectModel.virtualElementCalculatedBy: 'ABAP:ZCL_V'
  v : abap.char(1);
}
