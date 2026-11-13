@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity zi_twice as select from zt_one as a
  inner many to one join zt_one as b on b.k = a.k
{
  key a.k as K,
  a.f as F,
  key b.g as G,
  case a.f when 'A' then 1 end as Cs,
  @ObjectModel.text.association: '_Ghost'
  a.t as T
}
