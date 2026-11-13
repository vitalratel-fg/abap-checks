@AccessControl.authorizationCheck: #CHECK
@UI.headerInfo.typeName: 'X'
define view entity zc_view as select from zi_toone as b
  association of many to one zi_twice as _One on _One.K = b.K
{
  key b.K,
  b.companycode as companycode,
  concat(b.K, b.K) as plain_name,
  _One
}
